"""Запросы, общие для модулей каталога и поиска: опознание олимпиады и строки льгот."""

from typing import Any

from olymp_domain import squash
from olymp_domain.profile_query import collapse_profiles, match_profiles, split_query
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Row, fetch_all

BENEFIT_ORDER = ["БВИ", "100 баллов", "Особое право (БВИ/100)", "Фаст-трек", "ИД (доп. баллы)"]

BENEFIT_FIELDS = """
    b.id, b.benefit_type, b.raw_conditions_text, b.layer, b.olympiad_profile,
    b.olympiad_subject, b.level, b.winner_role, b.grade, b.confirm_subject,
    b.min_ege, b.award_subject, b.years, b.note, b.source_title, b.source_url, b.source_sheet,
    b.row_key,
    (SELECT max(r.resolved_at) FROM data_reports r
     WHERE r.kind = 'benefit' AND r.status = 'fixed' AND r.row_key = b.row_key) AS fixed_at
"""

OLYMPIAD_FIELDS = """o.id, o.canonical_name, o.short_name, o.kind, o.mentions,
                     o.bvi_count, o.sto_count, o.uni_count, o.in_rsosh_2026_27"""


async def resolve_olympiads(session: AsyncSession, q: str, limit: int = 12) -> list[Row]:
    """Находит олимпиады по свободному вводу: «вышка», «всош», «покори воробьевы».

    Ключ — только буквы (squash), поэтому опечатки в пробелах, кавычках и регистре не мешают.
    Ранг: 0 — точное совпадение сокращения, 1 — по началу, 2 — по вхождению, 3 — запрос
    длиннее сокращения и содержит его целиком.
    """
    key = squash(q)
    if len(key) < 2:
        return []
    return await fetch_all(
        session,
        f"""SELECT {OLYMPIAD_FIELDS},
                   MIN(CASE
                         WHEN a.squash_alias = :key THEN 0
                         WHEN a.squash_alias LIKE :prefix THEN 1
                         WHEN strpos(a.squash_alias, :key) > 0 THEN 2
                         ELSE 3 END) AS rank
            FROM olympiads o JOIN olympiad_aliases a ON a.olympiad_id = o.id
            WHERE a.squash_alias = :key OR a.squash_alias LIKE :prefix
                  OR strpos(a.squash_alias, :key) > 0
                  OR (length(a.squash_alias) >= 4 AND strpos(:key, a.squash_alias) > 0)
            GROUP BY o.id
            ORDER BY rank ASC, o.mentions DESC, o.id
            LIMIT :limit""",
        {"key": key, "prefix": key + "%", "limit": limit},
    )


# профиль в запросе принимаем, если он совпал хотя бы по началу слова («матем», «интеллект»)
MIN_PROFILE_SCORE = 50


async def resolve_olympiad_profiles(session: AsyncSession, q: str, limit: int = 3) -> list[Row]:
    """«нто ии», «высшая проба матем»: олимпиада и остаток запроса, разобранный как профиль.

    Возвращает олимпиады (как resolve_olympiads) с полями profile_id и profile_name, лучшие
    совпадения первыми. Остаток ищется среди профилей, которые видны на экране (без дублей).
    """
    key = squash(q)
    if len(key) < 4:
        return []
    aliases = await fetch_all(
        session,
        """SELECT DISTINCT olympiad_id, squash_alias FROM olympiad_aliases
           WHERE length(squash_alias) >= 2
                 AND length(:key) - length(squash_alias) >= 2
                 AND (strpos(:key, squash_alias) = 1
                      OR right(:key, length(squash_alias)) = squash_alias)""",
        {"key": key},
    )
    pairs = split_query(key, [(a["olympiad_id"], a["squash_alias"]) for a in aliases])
    hits: list[tuple[int, int, int, Row]] = []  # (-оценка, порядок, строки, профиль)
    profiles_of: dict[int, list[Row]] = {}
    for order, (olympiad_id, rest) in enumerate(pairs[:12]):
        if olympiad_id not in profiles_of:
            all_profiles = await fetch_all(
                session,
                """SELECT id, olympiad_id, name, mentions, level_2026_27 FROM olympiad_profiles
                   WHERE olympiad_id = :id""",
                {"id": olympiad_id},
            )
            profiles_of[olympiad_id] = collapse_profiles(all_profiles)[0]
        for profile, score in match_profiles(rest, profiles_of[olympiad_id]):
            if score >= MIN_PROFILE_SCORE:
                hits.append((-score, order, -profile["mentions"], profile))
    hits.sort(key=lambda h: h[:3])
    chosen, seen = [], set()
    for _, _, _, profile in hits:
        if profile["id"] not in seen:
            seen.add(profile["id"])
            chosen.append(profile)
    chosen = chosen[:limit]
    if not chosen:
        return []
    olympiads = {
        o["id"]: o
        for o in await fetch_all(
            session,
            f"SELECT {OLYMPIAD_FIELDS} FROM olympiads o WHERE o.id = ANY(:ids)",
            {"ids": list({p["olympiad_id"] for p in chosen})},
        )
    }
    return [
        {**olympiads[p["olympiad_id"]], "profile_id": p["id"], "profile_name": p["name"]}
        for p in chosen
    ]


async def olympiads_for_benefits(
    session: AsyncSession, benefit_ids: list[int]
) -> dict[int, list[dict[str, Any]]]:
    """Олимпиады каждой строки льготы; первой идёт самая упоминаемая."""
    if not benefit_ids:
        return {}
    rows = await fetch_all(
        session,
        """SELECT bo.benefit_id, o.id, o.short_name, o.canonical_name, o.kind
           FROM benefit_olympiads bo JOIN olympiads o ON o.id = bo.olympiad_id
           WHERE bo.benefit_id = ANY(:ids)
           ORDER BY o.mentions DESC, bo.benefit_id, bo.id""",
        {"ids": benefit_ids},
    )
    out: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(row["benefit_id"], []).append(
            {
                "id": row["id"],
                "short_name": row["short_name"],
                "canonical_name": row["canonical_name"],
                "kind": row["kind"],
            }
        )
    return out


def serialize_benefit(row: Row, olympiads: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": row["id"],
        "benefit_type": row["benefit_type"],
        "layer": row["layer"],
        "derived": row["layer"] == "derived",
        "text": row["raw_conditions_text"],
        "olympiad_profile": row["olympiad_profile"],
        "olympiad_subject": row["olympiad_subject"],
        "level": row["level"],
        "winner_role": row["winner_role"],
        "grade": row["grade"],
        "confirm_subject": row["confirm_subject"],
        "min_ege": row["min_ege"],
        "award_subject": row["award_subject"],
        "years": row["years"],
        "note": row["note"],
        "source_title": row["source_title"],
        "source_url": row["source_url"],
        "source_sheet": row["source_sheet"],
        "row_key": row["row_key"],
        "fixed_at": row["fixed_at"],
        "olympiads": olympiads or [],
    }
