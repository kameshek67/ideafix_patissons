"""Двусторонний поиск льгот.

- by_program  — «ищу олимпиады под вуз»: таблицы льгот направления;
- by_olympiad — «куда поступить с моей олимпиадой»: список вузов и строки выбранного вуза.
"""

import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import fetch_all, fetch_one, scalar
from olymp_api.olympiads import (
    BENEFIT_FIELDS,
    BENEFIT_ORDER,
    OLYMPIAD_FIELDS,
    olympiads_for_benefits,
    resolve_olympiads,
    serialize_benefit,
)
from olymp_api.universities import UNIVERSITY_FIELDS, university_of

# ---------------------------------------------------------------- сценарий 1


async def by_program(session: AsyncSession, program_id: int) -> dict[str, Any]:
    program = await fetch_one(
        session,
        f"""SELECT p.id, p.faculty_or_direction, p.profile_name, p.code, p.note,
                   p.source_title, p.source_url, p.source_sheet, {UNIVERSITY_FIELDS}
            FROM programs p JOIN universities u ON u.id = p.university_id
            WHERE p.id = :id""",
        {"id": program_id},
    )
    if not program:
        raise HTTPException(status_code=404, detail="Направление не найдено")

    rows = await fetch_all(
        session,
        f"""SELECT {BENEFIT_FIELDS} FROM benefits b
            WHERE b.program_id = :id AND b.layer <> 'raw'
            ORDER BY CASE b.benefit_type
                        WHEN 'БВИ' THEN 0 WHEN '100 баллов' THEN 1
                        WHEN 'Особое право (БВИ/100)' THEN 2 WHEN 'Фаст-трек' THEN 3
                        ELSE 4 END,
                     b.level, b.id""",
        {"id": program_id},
    )
    links = await olympiads_for_benefits(session, [r["id"] for r in rows])

    groups: dict[str, dict[str, Any]] = {}
    notes: list[dict[str, str]] = []
    seen_notes: set[str] = set()
    olympiad_index: dict[int, dict[str, Any]] = {}

    def add_note(text: str, kind: str) -> None:
        text = (text or "").strip()
        if text and text not in seen_notes:
            seen_notes.add(text)
            notes.append({"kind": kind, "text": text})

    add_note(program["note"], "Условия направления")
    for row in rows:
        benefit = serialize_benefit(row, links.get(row["id"], []))
        if row["layer"] == "summary":
            # текстовое правило без названий олимпиад — в примечания, не в таблицу
            add_note(row["raw_conditions_text"], row["benefit_type"])
            add_note(row["note"], row["benefit_type"])
            continue
        group = groups.setdefault(
            row["benefit_type"], {"type": row["benefit_type"], "rows": [], "count": 0}
        )
        group["rows"].append(benefit)
        group["count"] += 1
        add_note(row["note"], row["benefit_type"])
        for olympiad in benefit["olympiads"]:
            entry = olympiad_index.setdefault(olympiad["id"], {**olympiad, "types": [], "count": 0})
            entry["count"] += 1
            if row["benefit_type"] not in entry["types"]:
                entry["types"].append(row["benefit_type"])

    ordered = [groups[t] for t in BENEFIT_ORDER if t in groups]
    olympiad_list = sorted(olympiad_index.values(), key=lambda o: (-o["count"], o["short_name"]))

    return {
        "program": {
            k: program[k]
            for k in (
                "id",
                "faculty_or_direction",
                "profile_name",
                "code",
                "note",
                "source_title",
                "source_url",
                "source_sheet",
            )
        },
        "university": university_of(program),
        "groups": ordered,
        "notes": notes,
        "olympiads": olympiad_list,
        "sources": await program_sources(session, program),
        "total_benefits": sum(g["count"] for g in ordered),
    }


async def program_sources(session: AsyncSession, program: dict[str, Any]) -> list[dict[str, Any]]:
    """Источники в порядке надёжности: сначала стабильная страница раздела вуза
    (её адрес живёт годами), потом конкретные файлы, найденные на ней."""
    sources: list[dict[str, Any]] = []
    if program["docs_url"]:
        sources.append(
            {
                "title": program["docs_title"] or "Документы приёмной комиссии",
                "url": program["docs_url"],
                "kind": "page",
                "types": [],
            }
        )
    for row in await fetch_all(
        session,
        """SELECT title, url, checked_at FROM university_documents
           WHERE university_id = :uid ORDER BY id LIMIT 4""",
        {"uid": program["university_id"]},
    ):
        sources.append(
            {
                "title": row["title"],
                "url": row["url"],
                "kind": "file",
                "checked_at": row["checked_at"],
                "types": [],
            }
        )
    if sources:
        return sources

    seen_urls: dict[str, dict[str, Any]] = {}
    for row in await fetch_all(
        session,
        """SELECT (array_agg(source_title ORDER BY id))[1] AS source_title, source_url,
                  string_agg(DISTINCT benefit_type, ',') AS types
           FROM benefits WHERE program_id = :id AND source_url <> '' AND layer <> 'raw'
           GROUP BY source_url ORDER BY source_url""",
        {"id": program["id"]},
    ):
        seen_urls[row["source_url"]] = {
            "title": row["source_title"],
            "url": row["source_url"],
            "kind": "file",
            "types": (row["types"] or "").split(","),
        }
    if program["source_url"] and program["source_url"] not in seen_urls:
        seen_urls[program["source_url"]] = {
            "title": program["source_title"],
            "kind": "file",
            "url": program["source_url"],
            "types": [],
        }
    return list(seen_urls.values())


# ---------------------------------------------------------------- сценарий 2


async def by_olympiad(
    session: AsyncSession,
    q: str,
    olympiad_id: int | None,
    profile_id: int | None,
    university_id: int | None,
    region: str | None,
    benefit_type: str | None,
    limit: int,
) -> dict[str, Any]:
    if olympiad_id:
        one = await fetch_one(
            session,
            f"SELECT {OLYMPIAD_FIELDS} FROM olympiads o WHERE o.id = :id",
            {"id": olympiad_id},
        )
        matched = [one] if one else []
    else:
        matched = await resolve_olympiads(session, q)

    if not matched:
        return {
            "query": q,
            "matched_olympiads": [],
            "results": [],
            "total_programs": 0,
            "total_universities": 0,
            "profiles": [],
            "fallback": await fts_fallback(session, q, limit),
        }

    ids = [m["id"] for m in matched[:5]]

    # профили выбранной олимпиады — для чипов-фильтров на фронте
    profiles = await fetch_all(
        session,
        """SELECT id, olympiad_id, name, mentions, bvi_count, sto_count, uni_count
           FROM olympiad_profiles WHERE olympiad_id = ANY(:ids)
           ORDER BY mentions DESC, name, olympiad_id, id""",
        {"ids": ids},
    )
    without_profile = await scalar(
        session,
        """SELECT COUNT(*) FROM benefit_olympiads
           WHERE olympiad_id = ANY(:ids) AND profile_id IS NULL""",
        {"ids": ids},
    )

    params: dict[str, Any] = {"ids": ids}
    where = ["bo.olympiad_id = ANY(:ids)", "b.layer <> 'raw'"]
    if profile_id:
        where.append("bo.profile_id = :profile_id")
        params["profile_id"] = profile_id
    if university_id:
        where.append("u.id = :university_id")
        params["university_id"] = university_id
    if region and region != "Все":
        where.append("u.region_group = :region")
        params["region"] = region
    if benefit_type and benefit_type != "Все":
        where.append("b.benefit_type = :benefit_type")
        params["benefit_type"] = benefit_type
    condition = " AND ".join(where)

    # точные итоги считаем агрегатом — выдача ниже ограничена лимитом
    totals = await fetch_all(
        session,
        f"""SELECT u.id AS university_id, COUNT(DISTINCT p.id) AS programs_total,
                   SUM(CASE WHEN b.benefit_type = 'БВИ' THEN 1 ELSE 0 END) AS bvi,
                   SUM(CASE WHEN b.benefit_type = '100 баллов' THEN 1 ELSE 0 END) AS sto,
                   SUM(CASE WHEN b.benefit_type NOT IN ('БВИ', '100 баллов') THEN 1 ELSE 0 END)
                       AS other
            FROM benefit_olympiads bo
            JOIN benefits b ON b.id = bo.benefit_id
            JOIN programs p ON p.id = b.program_id
            JOIN universities u ON u.id = p.university_id
            WHERE {condition}
            GROUP BY u.id""",
        params,
    )
    totals_by_university = {row["university_id"]: row for row in totals}
    programs_total = sum(row["programs_total"] for row in totals)

    rows = await fetch_all(
        session,
        f"""SELECT {BENEFIT_FIELDS},
                   p.id AS program_id, p.faculty_or_direction, p.profile_name, p.code,
                   p.note AS program_note, p.source_url AS program_url,
                   p.source_title AS program_source_title, {UNIVERSITY_FIELDS},
                   o.id AS olympiad_id, o.short_name AS olympiad_short,
                   bo.profile_id AS matched_profile_id,
                   COALESCE(pr.name, bo.profile) AS matched_profile, bo.level AS matched_level,
                   bo.winner_role AS matched_role, bo.matched_via
            FROM benefit_olympiads bo
            JOIN olympiads o ON o.id = bo.olympiad_id
            LEFT JOIN olympiad_profiles pr ON pr.id = bo.profile_id
            JOIN benefits b ON b.id = bo.benefit_id
            JOIN programs p ON p.id = b.program_id
            JOIN universities u ON u.id = p.university_id
            WHERE {condition}
            ORDER BY u.region_group, u.name, p.sort_order, p.id,
                     CASE b.benefit_type WHEN 'БВИ' THEN 0 WHEN '100 баллов' THEN 1 ELSE 2 END,
                     b.id, bo.olympiad_id, bo.id
            LIMIT :row_limit""",
        {**params, "row_limit": limit * 15},
    )

    universities_map: dict[int, dict[str, Any]] = {}
    programs_seen: dict[int, dict[str, Any]] = {}
    for row in rows:
        aggregate = totals_by_university.get(row["university_id"], {})
        uni = universities_map.setdefault(
            row["university_id"],
            {
                "university": university_of(row),
                "programs": [],
                "programs_total": aggregate.get("programs_total", 0),
                "bvi": aggregate.get("bvi", 0),
                "sto": aggregate.get("sto", 0),
                "other": aggregate.get("other", 0),
            },
        )
        program = programs_seen.get(row["program_id"])
        if program is None:
            if len(programs_seen) >= limit:
                continue
            program = {
                "program": {
                    "id": row["program_id"],
                    "faculty_or_direction": row["faculty_or_direction"],
                    "profile_name": row["profile_name"],
                    "code": row["code"],
                    "note": row["program_note"],
                    "source_url": row["program_url"],
                    "source_title": row["program_source_title"],
                },
                "benefits": [],
                "types": [],
            }
            programs_seen[row["program_id"]] = program
            uni["programs"].append(program)
        benefit = serialize_benefit(
            row, [{"id": row["olympiad_id"], "short_name": row["olympiad_short"]}]
        )
        benefit["matched"] = {
            "profile": row["matched_profile"],
            "profile_id": row["matched_profile_id"],
            "level": row["matched_level"],
            "role": row["matched_role"],
            "via": row["matched_via"],
        }
        if not any(b["id"] == benefit["id"] for b in program["benefits"]):
            program["benefits"].append(benefit)
        if row["benefit_type"] not in program["types"]:
            program["types"].append(row["benefit_type"])

    # вузы, у которых все направления не влезли в лимит выдачи, всё равно показываем в списке
    for aggregate_university_id, aggregate in totals_by_university.items():
        if aggregate_university_id in universities_map:
            continue
        info = await fetch_one(
            session,
            """SELECT id, name, short_name, region, city, note, region_group
               FROM universities WHERE id = :id""",
            {"id": aggregate_university_id},
        )
        if info:
            universities_map[aggregate_university_id] = {
                "university": info,
                "programs": [],
                "programs_total": aggregate["programs_total"],
                "bvi": aggregate["bvi"],
                "sto": aggregate["sto"],
                "other": aggregate["other"],
            }

    results = sorted(
        universities_map.values(),
        key=lambda u: (-(u["bvi"] + u["sto"] + u["other"]), u["university"]["name"]),
    )
    return {
        "query": q,
        "matched_olympiads": matched,
        "profiles": profiles,
        "profile_id": profile_id,
        "without_profile": without_profile,
        "results": results,
        "total_programs": programs_total,
        "shown_programs": len(programs_seen),
        "total_universities": len(results),
        "truncated": len(programs_seen) < programs_total,
    }


# ---------------------------------------------------------------- запасной поиск

# токен — буквы и цифры (подчёркивание — разделитель, как у токенизатора unicode61)
RE_TOKEN_PART = re.compile(r"[^\W_]+")


def tsquery_for(q: str) -> str | None:
    """Запрос «высшая-проба воробь» -> 'высшая' <-> 'проба':* & 'воробь':*.

    Каждое слово ищется по началу; слово со знаками внутри — как фраза (так понимал
    такие запросы полнотекстовый индекс прототипа).
    """
    terms = []
    for token in q.replace('"', " ").split():
        if len(token) < 2:
            continue
        parts = RE_TOKEN_PART.findall(token.lower())
        if not parts:
            continue
        quoted = [f"'{part}'" for part in parts]
        quoted[-1] += ":*"
        terms.append(" <-> ".join(quoted))
    return " & ".join(terms) or None


async def fts_fallback(session: AsyncSession, q: str, limit: int) -> list[dict[str, Any]]:
    """Если олимпиада не опознана — полнотекстовый поиск по условиям."""
    query = tsquery_for(q)
    if not query:
        return []
    return await fetch_all(
        session,
        """SELECT si.benefit_id AS id, b.benefit_type, b.raw_conditions_text AS text,
                  p.id AS program_id, p.faculty_or_direction, u.name AS university
           FROM search_index si
           JOIN benefits b ON b.id = si.benefit_id
           JOIN programs p ON p.id = b.program_id
           JOIN universities u ON u.id = p.university_id
           WHERE si.document @@ to_tsquery('simple', :query)
           ORDER BY si.benefit_id
           LIMIT :limit""",
        {"query": query, "limit": min(limit, 50)},
    )
