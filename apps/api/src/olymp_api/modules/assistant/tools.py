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
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import fetch_all
from olymp_api.modules.achievements import service as achievements
from olymp_api.modules.catalog import service as catalog
from olymp_api.modules.search import service as search

log = structlog.get_logger()

MAX_RESULT_BYTES = 4096
MAX_KEYWORDS = 6
ROWS = 12
NO_DATA = "В базе нет данных. Это не значит, что льготы нет: нужно проверить на сайте вуза."


@dataclass
class ToolContext:
    session: AsyncSession
    diplomas: list[str]


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


def compact(payload: dict[str, Any], items_key: str) -> str:
    """JSON не больше MAX_RESULT_BYTES: лишние строки отбрасываются с конца."""
    items = list(payload.get(items_key) or [])
    while True:
        text = dumps({**payload, items_key: items})
        if len(text.encode()) <= MAX_RESULT_BYTES:
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


async def find_profiles(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    raw = args.get("keywords")
    if not isinstance(raw, list) or not raw:
        raise ValueError("нужен список keywords")
    keys = [key for key in (squash(str(word)) for word in raw[:MAX_KEYWORDS]) if len(key) >= 3]
    if not keys:
        raise ValueError("ключевые слова слишком короткие")
    # названия в collation C: регистр кириллицы не сворачивается, поэтому сравниваем по squash_key
    rows = await fetch_all(
        ctx.session,
        """SELECT p.id AS profile_id, p.name AS profile, p.level, p.bvi_count, p.sto_count,
                  p.uni_count, o.id AS olympiad_id, o.short_name, o.canonical_name
           FROM olympiad_profiles p JOIN olympiads o ON o.id = p.olympiad_id
           WHERE p.bvi_count + p.sto_count > 0
             AND EXISTS (SELECT 1 FROM unnest(CAST(:keys AS text[])) AS k
                         WHERE strpos(p.squash_key, k) > 0)
           ORDER BY p.bvi_count + p.sto_count DESC, p.id
           LIMIT :limit""",
        {"keys": keys, "limit": ROWS},
    )
    items = [
        {
            "olympiad_id": r["olympiad_id"],
            "olympiad": r["short_name"],
            "profile_id": r["profile_id"],
            "profile": r["profile"],
            "level": r["level"],
            "bvi_rows": r["bvi_count"],
            "sto_rows": r["sto_count"],
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
            entity("olympiad", r["olympiad_id"], r["short_name"], r["profile"], r["canonical_name"])
            for r in rows
        ],
    )


async def find_olympiads(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    query = str(args.get("query") or "").strip()
    if len(query) < 2:
        raise ValueError("нужен query")
    found = (await catalog.olympiads(ctx.session, query, False, 8))["items"]
    items = [
        {
            "olympiad_id": o["id"],
            "olympiad": o["short_name"],
            "name": o["canonical_name"],
            "bvi_rows": o["bvi_count"],
            "sto_rows": o["sto_count"],
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


async def universities_for_olympiad(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    olympiad_id = need_int(args, "olympiad_id")
    data = await search.by_olympiad(
        ctx.session,
        "олимпиада",  # запрос нужен сервису, но при известном id не используется
        olympiad_id,
        optional_int(args, "profile_id"),
        None,
        args.get("region") or None,
        args.get("benefit_type") or None,
        40,
    )
    if not data["matched_olympiads"]:
        return error("Олимпиада с таким id не найдена: сначала вызови поиск")
    olympiad = data["matched_olympiads"][0]
    results = data["results"][:ROWS]
    items, entities, sources = [], [], []
    for result in results:
        info = result["university"]
        name = university_name(info)
        examples = [p["program"]["faculty_or_direction"] for p in result["programs"][:2]]
        items.append(
            {
                "university_id": info["id"],
                "university": name,
                "city": info.get("city"),
                "programs": result["programs_total"],
                "bvi_rows": result["bvi"],
                "sto_rows": result["sto"],
                "examples": examples,
            }
        )
        entities.append(entity("university", info["id"], name, None, str(info.get("name") or "")))
        for program in result["programs"][:1]:
            sources.append(
                source(
                    program["program"]["source_url"],
                    program["program"]["source_title"],
                    name,
                    str(info.get("name") or ""),
                )
            )
    payload: dict[str, Any] = {
        "olympiad": olympiad["short_name"],
        "total_universities": data["total_universities"],
        "total_programs": data["total_programs"],
        "universities": items,
    }
    if not items:
        payload["note"] = NO_DATA
    label = olympiad["short_name"]
    return ToolResult(
        compact(payload, "universities"),
        entities=[entity("olympiad", olympiad_id, label, None), *entities],
        sources=[s for s in sources if s],
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
    olympiads = data["olympiads"][:ROWS]
    title = str(program["faculty_or_direction"])
    name = university_name(university)
    payload: dict[str, Any] = {
        "university": name,
        "program": title,
        "code": program["code"],
        "olympiads": [
            {"olympiad_id": o["id"], "olympiad": o["short_name"], "types": o["types"]}
            for o in olympiads
        ],
        "other_programs_found": len(fitting) - 1,
    }
    if not olympiads:
        payload["note"] = NO_DATA
    found = [source(s["url"], s["title"], name, title) for s in data["sources"][:2]]
    return ToolResult(
        compact(payload, "olympiads"),
        entities=[
            entity("program", program["id"], title, name),
            *[entity("olympiad", o["id"], o["short_name"]) for o in olympiads],
        ],
        sources=[s for s in found if s],
    )


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
        compact(payload, "universities"),
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
    items = [
        {
            "university_id": u["id"],
            "university": university_name(u),
            "city": u["city"],
            "programs": u["programs"],
            "bvi_rows": u["bvi"],
            "sto_rows": u["sto"],
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
    "olympiads_for_program": olympiads_for_program,
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
        "предмете. Ключевые слова — основы слов: «робот», «программир», «биолог».",
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
        "universities_for_olympiad",
        "Вузы, где олимпиада даёт льготы. Id берутся из результатов поиска.",
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
        "Какие олимпиады дают льготы на направление вуза.",
        {"university": _STRING, "program_query": _STRING},
        "university",
        "program_query",
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
