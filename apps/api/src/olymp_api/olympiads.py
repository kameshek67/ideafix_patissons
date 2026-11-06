"""Запросы, общие для модулей каталога и поиска: опознание олимпиады и строки льгот."""

from typing import Any

from olymp_domain import squash
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Row, fetch_all

BENEFIT_ORDER = ["БВИ", "100 баллов", "Особое право (БВИ/100)", "Фаст-трек", "ИД (доп. баллы)"]

BENEFIT_FIELDS = """
    b.id, b.benefit_type, b.raw_conditions_text, b.layer, b.olympiad_profile,
    b.olympiad_subject, b.level, b.winner_role, b.grade, b.confirm_subject,
    b.min_ege, b.award_subject, b.years, b.note, b.source_title, b.source_url, b.source_sheet
"""

OLYMPIAD_FIELDS = """o.id, o.canonical_name, o.short_name, o.kind, o.mentions,
                     o.bvi_count, o.sto_count, o.uni_count"""


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
        "olympiads": olympiads or [],
    }
