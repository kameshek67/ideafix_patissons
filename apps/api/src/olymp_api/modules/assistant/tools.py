"""Инструменты модели: только чтение базы льгот.

Аргументы приходят от модели и считаются недоверенными. Результат — компактный JSON для модели
и отдельно карточки и источники: их показывает сервер, поэтому модель не может подставить свою
ссылку. Тексты с сайтов вузов тоже недоверенные и передаются как данные.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import structlog
from fastapi import HTTPException
from olymp_domain import squash
from olymp_domain.admission_rules import find_rules
from olymp_domain.diplomas import is_real_profile
from olymp_domain.interests import (
    display_name,
    expand_keywords,
    is_list_profile,
    phrase_matches,
    query_words,
    words_of,
)
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import fetch_all, fetch_one
from olymp_api.modules.achievements import service as achievements
from olymp_api.modules.catalog import service as catalog
from olymp_api.modules.search import service as search

from .conditions import (
    BY_PROFILE_LEGEND,
    DATA_NOTICE,
    DATA_YEAR,
    squeeze,
    summarize,
)

log = structlog.get_logger()

MAX_RESULT_BYTES = 4096
# ответы с условиями льгот длиннее: пять вузов с условиями полезнее двенадцати без них
MAX_CONDITIONS_BYTES = 8192
UNIVERSITIES_SHOWN = 8  # вузов с условиями; остальные — только названием
PROGRAMS_PER_UNIVERSITY = 3
LINES_PER_PROGRAM = 3
LINES_PER_OLYMPIAD = 3
OLYMPIADS_FOR_PROGRAM = 8
LINES_PER_PAIR = 12
PAIR_PROGRAMS = 6
OTHER_UNIVERSITIES = 8
WIDE_LIMIT = 300  # направлений в выдаче поиска: нужны условия не только первых вузов по алфавиту
MAX_KEYWORDS = 6
ROWS = 12
NO_DATA = "В базе нет данных. Это не значит, что льготы нет: нужно проверить на сайте вуза."
UNKNOWN_ID = (
    "Этого id нет ни в результатах поиска в этом ответе, ни в фактах прошлых ответов (пометки "
    "[olympiad_id=…] в системном сообщении). Не придумывай id: найди олимпиаду через "
    "find_profiles или find_olympiads"
)
UNKNOWN_REF = (
    "Этого {what} нет ни в результатах поиска в этом ответе, ни в фактах прошлых ответов. "
    "Сначала вызови universities_for_olympiad или olympiads_for_program и возьми id оттуда"
)


@dataclass
class ToolContext:
    """Один ответ помощника. Инструменты принимают только id, которые вернул поиск в этом
    ответе или которые сервер сам выдал в прошлых ответах (подписанный контекст диалога, C1):
    придуманные моделью id давали вузы чужой олимпиады («Ломоносов» под видом НТО)."""

    session: AsyncSession
    diplomas: list[str]
    olympiads: set[int] = field(default_factory=set)
    profiles: dict[int, int] = field(default_factory=dict)  # профиль → его олимпиада
    programs: set[int] = field(default_factory=set)  # направления из выдачи инструментов
    universities: set[int] = field(default_factory=set)  # вузы из выдачи инструментов


@dataclass
class ToolResult:
    content: str
    # у карточек и источников служебное поле match: по нему ищем упоминание в ответе
    entities: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)


def entity(kind: str, id_: int, label: str, hint: str | None = None, *also: str) -> dict[str, Any]:
    return {"kind": kind, "id": id_, "label": label, "hint": hint, "match": [label, *also]}


def source(url: str | None, title: str | None, *match: str) -> dict[str, Any] | None:
    url = (url or "").strip()
    if not url.lower().startswith(("https://", "http://")):
        return None
    return {"url": url, "title": (title or "Документ вуза").strip(), "match": list(match)}


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def compact(payload: dict[str, Any], items_key: str, limit: int = MAX_RESULT_BYTES) -> str:
    """JSON не больше limit байт: лишние строки отбрасываются с конца."""
    items = list(payload.get(items_key) or [])
    while True:
        text = dumps({**payload, items_key: items})
        if len(text.encode()) <= limit:
            return text
        if not items:
            return dumps({"error": "результат слишком большой"})
        items.pop()
        payload = {**payload, "truncated": True}


def error(message: str) -> ToolResult:
    return ToolResult(dumps({"error": message}))


def need_int(args: dict[str, Any], key: str) -> int:
    value = args.get(key)
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError(f"нужен числовой {key}")
    return int(value)


def optional_int(args: dict[str, Any], key: str) -> int | None:
    return need_int(args, key) if args.get(key) not in (None, "", 0) else None


def university_name(u: dict[str, Any]) -> str:
    return str(u.get("short_name") or u.get("name") or "")


def benefit_kinds(bvi: int, sto: int) -> list[str]:
    """Какие льготы есть. Число строк базы ученику ничего не говорит, а модель его пересказывала:
    «28 строк с БВИ». Сколько вузов и направлений — в соседних полях."""
    return [kind for kind, count in (("БВИ", bvi), ("100 баллов", sto)) if count]


def track_for(
    words: list[str], profile: list[str], tracks: list[dict[str, Any]]
) -> tuple[bool, str | None]:
    """Подходит ли профиль теме и по какому треку. Трек ищется по названию и ключевым темам:
    у «Юниора» профиль «инженерные науки», а секция «разработка мобильных приложений под Android»
    есть только в треках."""
    by_profile = phrase_matches(words, profile)
    for track in tracks:
        if phrase_matches(words, words_of(f"{track['name']} {' '.join(track['topics'])}")):
            return True, str(track["name"])
    return by_profile, None


def pick_profiles(
    themes: list[list[str]],
    rows: list[dict[str, Any]],
    tracks: dict[int, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Профили под темы ученика: у каждой темы свой список, и списки берутся по очереди.

    Иначе общая тема («информатика», сотни строк льгот) вытесняла конкретную («мобильные
    приложения» у НТО). Сначала — фразы из нескольких слов, внутри темы — профили, которые
    дают льготы в большем числе вузов. Обрывки разбора таблиц и дубли с опечаткой пропускаются.
    Профиль подходит и по названию трека: в строке тогда поле track.
    """
    tracks = tracks or {}
    candidates = [
        (row, words_of(row["profile"]), tracks.get(row["profile_id"], []))
        for row in rows
        if is_real_profile(row["profile"]) and not is_list_profile(row["profile"])
    ]
    per_theme = []
    for words in sorted(themes, key=len, reverse=True):
        found = []
        for row, name_words, own_tracks in candidates:
            hit, track = track_for(words, name_words, own_tracks)
            if hit:
                found.append({**row, "track": track})
        found.sort(
            key=lambda r: (-r["uni_count"], -(r["bvi_count"] + r["sto_count"]), r["profile_id"])
        )
        per_theme.append(found)
    picked: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    while len(picked) < ROWS and any(per_theme):
        for found in per_theme:
            while found:
                row = found.pop(0)
                key = (row["olympiad_id"], squash(display_name(row["profile"])))
                if key not in seen:
                    seen.add(key)
                    picked.append(row)
                    break
            if len(picked) >= ROWS:
                break
    return picked


async def find_profiles(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    raw = args.get("keywords")
    if not isinstance(raw, list) or not raw:
        raise ValueError("нужен список keywords")
    keywords = expand_keywords([str(k) for k in raw[:MAX_KEYWORDS]])
    themes = [words for words in (query_words(k) for k in keywords) if words]
    if not themes:
        raise ValueError("ключевые слова слишком короткие")
    # профилей с льготами несколько сотен: сопоставляем по основам слов в коде, а не в SQL
    tracks: dict[int, list[dict[str, Any]]] = {}
    for track in await fetch_all(
        ctx.session, "SELECT profile_id, name, topics FROM olympiad_tracks ORDER BY id"
    ):
        tracks.setdefault(track["profile_id"], []).append(track)
    rows = pick_profiles(
        themes,
        await fetch_all(
            ctx.session,
            """SELECT p.id AS profile_id, p.name AS profile, p.level, p.bvi_count, p.sto_count,
                      p.uni_count, o.id AS olympiad_id, o.short_name, o.canonical_name
               FROM olympiad_profiles p JOIN olympiads o ON o.id = p.olympiad_id
               WHERE p.bvi_count + p.sto_count > 0
               ORDER BY p.id""",
        ),
        tracks,
    )
    ctx.olympiads.update(r["olympiad_id"] for r in rows)
    ctx.profiles.update((r["profile_id"], r["olympiad_id"]) for r in rows)
    items = [
        {
            "olympiad_id": r["olympiad_id"],
            "olympiad": r["short_name"],
            "profile_id": r["profile_id"],
            "profile": display_name(r["profile"]),
            **({"track": r["track"]} if r["track"] else {}),
            "level": r["level"],
            "benefits": benefit_kinds(r["bvi_count"], r["sto_count"]),
            "universities": r["uni_count"],
        }
        for r in rows
    ]
    payload: dict[str, Any] = {"profiles": items}
    if not items:
        payload["note"] = "По этим словам профилей нет. Попробуй другие слова или предмет."
    return ToolResult(
        compact(payload, "profiles"),
        entities=[
            entity(
                "olympiad",
                r["olympiad_id"],
                r["short_name"],
                display_name(r["profile"]),
                r["canonical_name"],
            )
            for r in rows
        ],
    )


async def find_olympiads(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    query = str(args.get("query") or "").strip()
    if len(query) < 2:
        raise ValueError("нужен query")
    found = (await catalog.olympiads(ctx.session, query, False, 8))["items"]
    ctx.olympiads.update(o["id"] for o in found)
    items = [
        {
            "olympiad_id": o["id"],
            "olympiad": o["short_name"],
            "name": o["canonical_name"],
            "benefits": benefit_kinds(o["bvi_count"], o["sto_count"]),
            "universities": o["uni_count"],
            "profiles": o.get("profiles", 0),
        }
        for o in found
    ]
    payload: dict[str, Any] = {"olympiads": items}
    if not items:
        payload["note"] = NO_DATA
    return ToolResult(
        compact(payload, "olympiads"),
        entities=[
            entity("olympiad", o["id"], o["short_name"], None, o["canonical_name"]) for o in found
        ],
    )


def with_notice(payload: dict[str, Any], by_profile: bool) -> dict[str, Any]:
    """Год данных и пояснение метки «по профилю» — во всех ответах с условиями льгот."""
    payload["data_year"] = DATA_YEAR
    payload["notice"] = DATA_NOTICE
    if by_profile:
        payload["legend"] = BY_PROFILE_LEGEND
    return payload


def condition_groups(programs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Направления вуза с одинаковыми условиями сливаются в одну запись: так короче."""
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    by_profile = False
    for program in programs:
        summary = summarize(program["benefits"], LINES_PER_PROGRAM)
        by_profile = by_profile or summary.by_profile
        key = (tuple(summary.lines), summary.conflict, summary.more)
        entry = merged.setdefault(key, {"programs": [], **summary.as_fields()})
        entry["programs"].append(squeeze(program["program"]["faculty_or_direction"], 120))
    return list(merged.values()), by_profile


def program_source(program: dict[str, Any]) -> dict[str, Any] | None:
    """Источник направления: его страница, а без неё — документ первой строки условий."""
    first = program["benefits"][0] if program["benefits"] else {}
    return source(
        program["program"]["source_url"] or first.get("source_url"),
        program["program"]["source_title"] or first.get("source_title"),
    )


async def universities_for_olympiad(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    olympiad_id = need_int(args, "olympiad_id")
    profile_id = optional_int(args, "profile_id")
    if olympiad_id not in ctx.olympiads:
        return error(UNKNOWN_ID)
    if profile_id is not None and ctx.profiles.get(profile_id) != olympiad_id:
        return error(
            "Этот profile_id не от этой олимпиады или не из поиска в этом ответе: возьми "
            "olympiad_id и profile_id из одной строки find_profiles"
        )
    data = await search.by_olympiad(
        ctx.session,
        "олимпиада",  # запрос нужен сервису, но при известном id не используется
        olympiad_id,
        profile_id,
        None,
        args.get("region") or None,
        args.get("benefit_type") or None,
        WIDE_LIMIT,
    )
    if not data["matched_olympiads"]:
        return error("Олимпиада с таким id не найдена: сначала вызови поиск")
    olympiad = data["matched_olympiads"][0]
    # вузы с условиями важнее вузов без них: у «хвоста» выдачи направления не загружены
    detailed = [r for r in data["results"] if r["programs"]]
    rest = [r for r in data["results"] if not r["programs"]]
    detailed, rest = detailed[:UNIVERSITIES_SHOWN], rest + detailed[UNIVERSITIES_SHOWN:]
    items, entities, sources = [], [], []
    by_profile = False
    for result in detailed:
        info = result["university"]
        name = university_name(info)
        ctx.universities.add(info["id"])
        ctx.programs.update(p["program"]["id"] for p in result["programs"])
        # сначала направления, где есть БВИ; порядок остальных сохраняется
        ranked = sorted(result["programs"], key=lambda p: "БВИ" not in p["types"])
        shown = ranked[:PROGRAMS_PER_UNIVERSITY]
        groups, derived = condition_groups(shown)
        by_profile = by_profile or derived
        items.append(
            {
                "university_id": info["id"],
                "university": name,
                "city": info.get("city"),
                "programs_total": result["programs_total"],
                "benefits": benefit_kinds(result["bvi"], result["sto"]),
                "directions": groups,
            }
        )
        entities.append(entity("university", info["id"], name, None, str(info.get("name") or "")))
        found = program_source(shown[0])
        if found:
            sources.append({**found, "match": [name, str(info.get("name") or "")]})
    more = []
    for result in rest[:OTHER_UNIVERSITIES]:
        info = result["university"]
        ctx.universities.add(info["id"])
        more.append({"university_id": info["id"], "university": university_name(info)})
    payload: dict[str, Any] = {
        "olympiad": olympiad["short_name"],
        "total_universities": data["total_universities"],
        "total_programs": data["total_programs"],
        "universities": items,
    }
    if more:
        payload["more_universities"] = more
        payload["more_hint"] = (
            "у этих вузов условия не показаны: возьми benefit_conditions с university_id"
        )
    if not items and not more:
        payload["note"] = NO_DATA
    label = olympiad["short_name"]
    return ToolResult(
        compact(with_notice(payload, by_profile), "universities", MAX_CONDITIONS_BYTES),
        entities=[entity("olympiad", olympiad_id, label, None), *entities],
        sources=[s for s in sources if s],
    )


async def olympiad_card(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    olympiad_id = need_int(args, "olympiad_id")
    if olympiad_id not in ctx.olympiads:
        return error(UNKNOWN_ID)
    info = await fetch_all(
        ctx.session,
        """SELECT o.short_name, o.canonical_name, i.site_url, i.summary, i.grades, i.formats,
                  i.stages, i.source_url, i.checked
           FROM olympiads o LEFT JOIN olympiad_info i ON i.olympiad_id = o.id
           WHERE o.id = :id""",
        {"id": olympiad_id},
    )
    if not info:
        return error("Олимпиада с таким id не найдена: сначала вызови поиск")
    card = info[0]
    label = card["short_name"]
    if not card["site_url"]:
        return ToolResult(
            dumps(
                {
                    "olympiad": label,
                    "note": "Карточки этой олимпиады в базе нет: формат, классы и секции "
                    "неизвестны. Не выдумывай их, посоветуй официальный сайт олимпиады.",
                }
            ),
            entities=[entity("olympiad", olympiad_id, label, None, card["canonical_name"])],
        )
    tracks = await fetch_all(
        ctx.session,
        """SELECT t.name, t.topics, p.id AS profile_id, p.name AS profile
           FROM olympiad_tracks t JOIN olympiad_profiles p ON p.id = t.profile_id
           WHERE t.olympiad_id = :id ORDER BY t.id""",
        {"id": olympiad_id},
    )
    for track in tracks:
        ctx.profiles[track["profile_id"]] = olympiad_id
    payload: dict[str, Any] = {
        "olympiad": label,
        "name": card["canonical_name"],
        "summary": card["summary"],
        "grades": card["grades"],
        "format": card["formats"] or "в карточке не указан",
        "stages": card["stages"] or "в карточке не указаны",
        "site": card["site_url"],
        "checked": str(card["checked"]),
        "tracks": [
            {
                "track": t["name"],
                "profile_id": t["profile_id"],
                "profile": display_name(t["profile"]),
                **({"topics": t["topics"]} if t["topics"] else {}),
            }
            for t in tracks
        ],
    }
    return ToolResult(
        compact(payload, "tracks"),
        entities=[entity("olympiad", olympiad_id, label, None, card["canonical_name"])],
        sources=[s for s in [source(card["source_url"], "Официальный сайт олимпиады", label)] if s],
    )


async def olympiads_for_program(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    needle = squash(str(args.get("university") or ""))
    query = str(args.get("program_query") or "").strip()
    query_key = squash(query)
    if len(needle) < 2 or not query_key:
        raise ValueError("нужны university и program_query")
    universities = (await catalog.universities(ctx.session, None, None))["items"]
    exact = [u for u in universities if squash(u["short_name"] or "") == needle]
    near = [u for u in universities if needle in squash(f"{u['short_name']} {u['name']}")]
    matched = exact or near
    if not matched:
        return ToolResult(dumps({"note": f"Вуз не найден. {NO_DATA}"}))
    university = matched[0]
    programs = (await catalog.programs(ctx.session, university["id"], None, 1000))["items"]
    fitting = [
        p
        for p in programs
        if query_key in squash(f"{p['faculty_or_direction']} {p['profile_name']}")
        or query == p["code"]
    ]
    if not fitting:
        return ToolResult(
            dumps(
                {"university": university_name(university), "note": f"Нет направления. {NO_DATA}"}
            )
        )
    program = max(fitting, key=lambda p: p["benefits"])
    data = await search.by_program(ctx.session, program["id"])
    # строки условий каждой олимпиады; одна строка вуза может относиться к нескольким олимпиадам
    rows_of: dict[int, list[dict[str, Any]]] = {}
    for group in data["groups"]:
        for row in group["rows"]:
            for linked in row["olympiads"]:
                rows_of.setdefault(linked["id"], []).append(row)
    # олимпиады, которые вуз назвал прямо, раньше выведенных «по профилю»
    olympiads = sorted(
        data["olympiads"],
        key=lambda o: (-sum(1 for r in rows_of.get(o["id"], []) if not r["derived"]), -o["count"]),
    )[:OLYMPIADS_FOR_PROGRAM]
    ctx.olympiads.update(o["id"] for o in olympiads)
    ctx.programs.add(program["id"])
    ctx.universities.add(university["id"])
    title = str(program["faculty_or_direction"])
    name = university_name(university)
    items, by_profile = [], False
    for o in olympiads:
        summary = summarize(rows_of.get(o["id"], []), LINES_PER_OLYMPIAD)
        by_profile = by_profile or summary.by_profile
        items.append(
            {
                "olympiad_id": o["id"],
                "olympiad": o["short_name"],
                "types": o["types"],
                **summary.as_fields(),
            }
        )
    payload: dict[str, Any] = {
        "university": name,
        "program_id": program["id"],
        "program": title,
        "code": program["code"],
        "total_olympiads": len(data["olympiads"]),
        "olympiads": items,
        "other_programs_found": len(fitting) - 1,
    }
    if not olympiads:
        payload["note"] = NO_DATA
    found = [source(s["url"], s["title"], name, title) for s in data["sources"][:2]]
    return ToolResult(
        compact(with_notice(payload, by_profile), "olympiads", MAX_CONDITIONS_BYTES),
        entities=[
            entity("program", program["id"], title, name),
            *[entity("olympiad", o["id"], o["short_name"]) for o in olympiads],
        ],
        sources=[s for s in found if s],
    )


async def benefit_conditions(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    """Точные условия одной пары «олимпиада × направление (или вуз)»: все строки и источник."""
    olympiad_id = need_int(args, "olympiad_id")
    program_id = optional_int(args, "program_id")
    university_id = optional_int(args, "university_id")
    profile_id = optional_int(args, "profile_id")
    if olympiad_id not in ctx.olympiads:
        return error(UNKNOWN_ID)
    if program_id is None and university_id is None:
        raise ValueError("нужен program_id или university_id")
    if profile_id is not None and ctx.profiles.get(profile_id) != olympiad_id:
        return error(
            "Этот profile_id не от этой олимпиады или не из поиска в этом ответе: возьми "
            "olympiad_id и profile_id из одной строки find_profiles"
        )
    if program_id is not None:
        if program_id not in ctx.programs:
            return error(UNKNOWN_REF.format(what="program_id"))
        row = await fetch_one(
            ctx.session, "SELECT university_id FROM programs WHERE id = :id", {"id": program_id}
        )
        if not row:
            return error("Направление с таким id не найдено")
        university_id = row["university_id"]
    elif university_id not in ctx.universities:
        return error(UNKNOWN_REF.format(what="university_id"))
    data = await search.by_olympiad(
        ctx.session, "олимпиада", olympiad_id, profile_id, university_id, None, None, WIDE_LIMIT
    )
    if not data["matched_olympiads"]:
        return error("Олимпиада с таким id не найдена: сначала вызови поиск")
    olympiad = data["matched_olympiads"][0]
    result = data["results"][0] if data["results"] else None
    found = [
        p
        for p in (result["programs"] if result else [])
        if program_id in (None, p["program"]["id"])
    ]
    found.sort(key=lambda p: "БВИ" not in p["types"])
    payload: dict[str, Any] = {"olympiad": olympiad["short_name"], "programs": []}
    entities = [entity("olympiad", olympiad_id, olympiad["short_name"], None)]
    sources: list[dict[str, Any] | None] = []
    by_profile = False
    if result:
        info = result["university"]
        name = university_name(info)
        payload["university"] = name
        entities.append(entity("university", info["id"], name, None, str(info.get("name") or "")))
        items = []
        for program in found[:PAIR_PROGRAMS]:
            summary = summarize(program["benefits"], LINES_PER_PAIR)
            by_profile = by_profile or summary.by_profile
            meta = program["program"]
            first = program["benefits"][0] if program["benefits"] else {}
            item = {
                "program_id": meta["id"],
                "program": squeeze(meta["faculty_or_direction"], 120),
                "code": meta["code"],
                **summary.as_fields(),
                "document": squeeze(meta["source_title"] or first.get("source_title"), 120),
            }
            if meta.get("note"):
                item["program_note"] = squeeze(meta["note"], 160)
            items.append(item)
            entities.append(entity("program", meta["id"], str(meta["faculty_or_direction"]), name))
            sources.append(program_source(program))
            # документы строк условий: они могут отличаться от страницы направления
            for benefit in program["benefits"]:
                sources.append(source(benefit.get("source_url"), benefit.get("source_title")))
        payload["programs"] = items
        payload["other_programs"] = max(0, len(found) - len(items))
    if not found:
        payload["note"] = "У этой пары в базе нет строк условий. " + NO_DATA
    unique: dict[str, dict[str, Any]] = {}
    for candidate in sources:
        if candidate:
            match = [payload.get("university") or ""]
            unique.setdefault(candidate["url"], {**candidate, "match": match})
    return ToolResult(
        compact(with_notice(payload, by_profile), "programs", MAX_CONDITIONS_BYTES),
        entities=entities,
        sources=list(unique.values())[:3],
    )


async def explain_rule(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    """Общие правила приёма из справочника: пункт, источник и дата проверки."""
    topic = squeeze(args.get("topic"), 200)
    if len(topic) < 2:
        raise ValueError("нужен topic")
    rules = find_rules(topic, limit=2)
    if not rules:
        return ToolResult(
            dumps(
                {
                    "topic": topic,
                    "rules": [],
                    "note": "В справочнике общих правил этого нет: смотри правила приёма вуза. "
                    "Не отвечай на это из общих знаний.",
                }
            )
        )
    payload: dict[str, Any] = {
        "rules": [
            {
                "topic": r.topic,
                "text": r.text,
                "source": squeeze(r.source_title, 160),
                "checked": r.checked.isoformat(),
            }
            for r in rules
        ]
    }
    found = [source(r.source_url, r.source_title, r.topic) for r in rules]
    return ToolResult(compact(payload, "rules"), sources=[s for s in found if s])


async def match_diplomas(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if not ctx.diplomas:
        return ToolResult(
            dumps({"note": "Дипломов нет или ученик выключил их учёт. Предложи вкладку «Дипломы»."})
        )
    specs = achievements.parse_specs(ctx.diplomas)
    data = await achievements.match_diplomas(ctx.session, specs, None, None)
    results = data["results"][:ROWS]
    items = [
        {
            "university_id": r["university"]["id"],
            "university": university_name(r["university"]),
            "programs": r["programs"],
            "bvi": r["bvi"],
            "sto": r["sto"],
            "to_check": r["check"],
        }
        for r in results
    ]
    ctx.universities.update(r["university"]["id"] for r in results)
    payload = {
        "totals": data["totals"],
        "diplomas": [
            {
                "olympiad": (d["olympiad"] or {}).get("short_name"),
                "found": d["found"],
                "expired": d["expired"],
                "role": d["role"],
            }
            for d in data["diplomas"]
        ],
        "universities": items,
    }
    return ToolResult(
        compact(with_notice(payload, False), "universities"),
        entities=[
            entity(
                "university",
                r["university"]["id"],
                university_name(r["university"]),
                None,
                str(r["university"].get("name") or ""),
            )
            for r in results
        ],
    )


async def list_universities(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    data = await catalog.universities(ctx.session, args.get("region") or None, None)
    needle = squash(str(args.get("query") or ""))
    found = [
        u for u in data["items"] if not needle or needle in squash(f"{u['short_name']} {u['name']}")
    ][:ROWS]
    ctx.universities.update(u["id"] for u in found)
    items = [
        {
            "university_id": u["id"],
            "university": university_name(u),
            "city": u["city"],
            "programs": u["programs"],
            "benefits": benefit_kinds(u["bvi"], u["sto"]),
        }
        for u in found
    ]
    return ToolResult(
        compact({"regions": data["regions"], "universities": items}, "universities"),
        entities=[
            entity("university", u["id"], university_name(u), None, str(u["name"])) for u in found
        ],
    )


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]

HANDLERS: dict[str, Handler] = {
    "find_profiles": find_profiles,
    "find_olympiads": find_olympiads,
    "universities_for_olympiad": universities_for_olympiad,
    "olympiad_card": olympiad_card,
    "olympiads_for_program": olympiads_for_program,
    "benefit_conditions": benefit_conditions,
    "explain_rule": explain_rule,
    "match_diplomas": match_diplomas,
    "list_universities": list_universities,
}


def _tool(
    name: str, description: str, properties: dict[str, Any], *required: str
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(required),
            },
        },
    }


_BENEFIT = {"type": "string", "enum": ["БВИ", "100 баллов"]}
_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}

TOOLS: list[dict[str, Any]] = [
    _tool(
        "find_profiles",
        "Ищет профили олимпиад по темам. Вызывай, когда ученик рассказывает об увлечениях или "
        "предмете. Каждая тема — слово или короткая фраза: «мобильные приложения», «робот», "
        "«биолог». Профиль находится, если в его названии есть все слова темы в любых формах. "
        "Конкретное увлечение передавай отдельной темой, а общий предмет — другой темой. Тема "
        "находит и секции олимпиад (поле track): у «Юниора» секция есть, хотя профиль называется "
        "шире.",
        {"keywords": {"type": "array", "items": _STRING, "maxItems": MAX_KEYWORDS}},
        "keywords",
    ),
    _tool(
        "find_olympiads",
        "Ищет олимпиаду по названию или сокращению: «вышка», «всош», «нто».",
        {"query": _STRING},
        "query",
    ),
    _tool(
        "olympiad_card",
        "Карточка олимпиады: что это, формат, классы, этапы, секции и официальный сайт. Для "
        "вопросов «что это», «как проходит», «где сайт». olympiad_id бери из поиска в этом "
        "ответе или из фактов прошлых ответов. Если карточки нет, так и скажи: формат и секции не "
        "выдумывай.",
        {"olympiad_id": _INTEGER},
        "olympiad_id",
    ),
    _tool(
        "universities_for_olympiad",
        "Вузы, где олимпиада даёт льготы, с условиями по направлениям: кому (победители, "
        "призёры), класс, подтверждающий предмет и порог ЕГЭ. olympiad_id и profile_id бери из "
        "результатов find_profiles или find_olympiads в этом ответе или из фактов прошлых ответов "
        "(пометки [olympiad_id=…]); других id не придумывай.",
        {
            "olympiad_id": _INTEGER,
            "profile_id": _INTEGER,
            "benefit_type": _BENEFIT,
            "region": _STRING,
        },
        "olympiad_id",
    ),
    _tool(
        "olympiads_for_program",
        "Какие олимпиады дают льготы на направление вуза, с условиями каждой: кому, класс, "
        "предмет и порог ЕГЭ.",
        {"university": _STRING, "program_query": _STRING},
        "university",
        "program_query",
    ),
    _tool(
        "benefit_conditions",
        "Точные условия льготы для пары «олимпиада × направление» или «олимпиада × вуз»: все "
        "строки с источником. Вызывай на вопросы «какой балл ЕГЭ», «а если я призёр», «какой "
        "класс». Id бери из результатов инструментов в этом ответе или из фактов прошлых "
        "ответов ([olympiad_id=…], [program_id=…], [university_id=…]): для уточнения по "
        "прошлому ответу повторный поиск не нужен. profile_id сужает профиль.",
        {
            "olympiad_id": _INTEGER,
            "program_id": _INTEGER,
            "university_id": _INTEGER,
            "profile_id": _INTEGER,
        },
        "olympiad_id",
    ),
    _tool(
        "explain_rule",
        "Общие правила приёма из справочника с источником: что такое БВИ, сколько действует "
        "диплом, подтверждение баллом ЕГЭ, уровни олимпиад, когда вузы публикуют правила. topic — "
        "вопрос ученика своими словами. Если в справочнике нет, так и скажи.",
        {"topic": _STRING},
        "topic",
    ),
    _tool("match_diplomas", "Где дипломы ученика дают льготы с учётом условий вуза.", {}),
    _tool(
        "list_universities",
        "Список вузов, можно отфильтровать по региону или названию.",
        {"region": _STRING, "query": _STRING},
    ),
]


async def run_tool(name: str, raw_arguments: str, ctx: ToolContext) -> ToolResult:
    """Выполняет вызов модели. Ошибка не роняет запрос: модель получает её как результат."""
    handler = HANDLERS.get(name)
    if handler is None:
        return error(f"Нет инструмента {name[:40]}")
    try:
        args = json.loads(raw_arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("аргументы должны быть объектом")
        return await handler(ctx, args)
    except (ValueError, TypeError) as exc:
        return error(f"Ошибка в аргументах: {exc}")
    except HTTPException as exc:
        return error(str(exc.detail))
    except Exception as exc:  # noqa: BLE001 - сбой инструмента не должен обрывать ответ
        log.exception("assistant_tool_failed", tool=name, error=type(exc).__name__)
        await ctx.session.rollback()
        return error("Поиск сейчас не сработал")
