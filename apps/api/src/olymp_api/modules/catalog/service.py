"""Справочники: статистика базы, регионы, вузы, направления, олимпиады и их профили."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import fetch_all, fetch_one, scalar
from olymp_api.olympiads import OLYMPIAD_FIELDS, resolve_olympiads

REGION_ORDER = {"Москва": 0, "Санкт-Петербург": 1, "Регионы": 2}

# число направлений и льгот (без слоя raw) по вузу
UNIVERSITY_COUNTERS = """COUNT(DISTINCT p.id) AS programs,
                         SUM(CASE WHEN b.benefit_type = 'БВИ' THEN 1 ELSE 0 END) AS bvi,
                         SUM(CASE WHEN b.benefit_type = '100 баллов' THEN 1 ELSE 0 END) AS sto,
                         COUNT(b.id) AS benefits,
                         SUM(CASE WHEN b.layer IN ('detailed', 'derived') THEN 1 ELSE 0 END)
                             AS table_rows"""


async def stats(session: AsyncSession) -> dict[str, Any]:
    meta = {r["key"]: r["value"] for r in await fetch_all(session, "SELECT key, value FROM meta")}
    by_type = await fetch_all(
        session,
        """SELECT benefit_type, COUNT(*) AS cnt FROM benefits WHERE layer <> 'raw'
           GROUP BY benefit_type""",
    )
    by_university = await fetch_all(
        session,
        f"""SELECT u.id, u.name, u.short_name, u.region, u.city, u.region_group,
                   {UNIVERSITY_COUNTERS}
            FROM universities u
            LEFT JOIN programs p ON p.university_id = u.id
            LEFT JOIN benefits b ON b.program_id = p.id AND b.layer <> 'raw'
            GROUP BY u.id ORDER BY benefits DESC, u.id""",
    )
    top_olympiads = await fetch_all(
        session,
        """SELECT id, short_name, canonical_name, mentions, bvi_count, sto_count, uni_count
           FROM olympiads ORDER BY mentions DESC, id LIMIT 15""",
    )
    sheets = await fetch_all(
        session,
        "SELECT sheet, rows_read, rows_ingested, benefits, comment FROM ingest_log ORDER BY id",
    )

    def count(key: str) -> int:
        return int(meta.get(key, 0))

    return {
        "totals": {
            "universities": count("universities"),
            "programs": count("programs"),
            "benefits": count("benefits"),
            "bvi": count("benefits_bvi"),
            "sto": count("benefits_sto"),
            "olympiads": count("olympiads"),
            "profiles": count("profiles"),
            "links": count("links"),
            "keywords": count("keywords"),
            "rows": count("benefits_rows"),
            "derived": count("benefits_derived"),
            "notes": count("benefits_notes"),
        },
        "source_file": meta.get("source_file", ""),
        "built_at": meta.get("built_at", ""),
        "benefit_types": {r["benefit_type"]: r["cnt"] for r in by_type},
        "universities": by_university,
        "top_olympiads": top_olympiads,
        "sheets": sheets,
    }


async def regions(session: AsyncSession) -> dict[str, Any]:
    rows = await fetch_all(
        session,
        """SELECT region_group, region, COUNT(*) AS universities
           FROM universities GROUP BY region_group, region ORDER BY region_group, region""",
    )
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        group = groups.setdefault(
            row["region_group"], {"name": row["region_group"], "universities": 0, "regions": []}
        )
        group["universities"] += row["universities"]
        group["regions"].append(row["region"])
    return {"items": sorted(groups.values(), key=lambda g: REGION_ORDER.get(g["name"], 9))}


# Текстовые колонки в COLLATE "C" (models.CText): в ней ILIKE не складывает регистр кириллицы.
# Сравниваем в сортировке базы по умолчанию (en_US.utf8 в образе Postgres).
def ilike(column: str) -> str:
    return f'{column} COLLATE "default" ILIKE :q'


def contains(q: str) -> str:
    """Шаблон ILIKE «где-то внутри»: % и _ из запроса ищутся как обычные символы."""
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def universities(session: AsyncSession, region: str | None, q: str | None) -> dict[str, Any]:
    where, params = [], {}
    if region and region != "Все":
        where.append("u.region_group = :region")
        params["region"] = region
    if q:
        # без учёта регистра: «мгу» находит МГУ
        where.append(f"({ilike('u.name')} OR {ilike('u.short_name')})")
        params["q"] = contains(q)
    items = await fetch_all(
        session,
        f"""SELECT u.id, u.name, u.short_name, u.region, u.city, u.note, u.region_group,
                   {UNIVERSITY_COUNTERS}
            FROM universities u
            LEFT JOIN programs p ON p.university_id = u.id
            LEFT JOIN benefits b ON b.program_id = p.id AND b.layer <> 'raw'
            {"WHERE " + " AND ".join(where) if where else ""}
            GROUP BY u.id ORDER BY benefits DESC, u.name""",
        params,
    )
    region_names = [r["name"] for r in (await regions(session))["items"]]
    return {"count": len(items), "items": items, "regions": region_names}


async def programs(
    session: AsyncSession, university_id: int | None, q: str | None, limit: int
) -> dict[str, Any]:
    where: list[str] = []
    params: dict[str, Any] = {"limit": limit}
    if university_id:
        where.append("p.university_id = :university_id")
        params["university_id"] = university_id
    if q:
        columns = ("p.faculty_or_direction", "p.profile_name", "p.code")
        where.append("(" + " OR ".join(ilike(c) for c in columns) + ")")
        params["q"] = contains(q)
    items = await fetch_all(
        session,
        f"""SELECT p.id, p.university_id, p.faculty_or_direction, p.profile_name, p.code,
                   p.note, p.source_url, p.source_sheet, u.name AS university,
                   u.short_name AS university_short, u.region, u.region_group,
                   SUM(CASE WHEN b.benefit_type = 'БВИ' THEN 1 ELSE 0 END) AS bvi,
                   SUM(CASE WHEN b.benefit_type = '100 баллов' THEN 1 ELSE 0 END) AS sto,
                   COUNT(b.id) AS benefits,
                   SUM(CASE WHEN b.layer IN ('detailed', 'derived') THEN 1 ELSE 0 END)
                       AS table_rows
            FROM programs p
            JOIN universities u ON u.id = p.university_id
            LEFT JOIN benefits b ON b.program_id = p.id AND b.layer <> 'raw'
            {"WHERE " + " AND ".join(where) if where else ""}
            GROUP BY p.id, u.id
            ORDER BY p.sort_order, p.faculty_or_direction, p.id LIMIT :limit""",
        params,
    )
    return {"count": len(items), "items": items}


async def olympiads(
    session: AsyncSession, q: str | None, featured: bool, limit: int
) -> dict[str, Any]:
    if q:
        items = await resolve_olympiads(session, q, limit)
    else:
        items = await fetch_all(
            session,
            f"""SELECT {OLYMPIAD_FIELDS.replace("o.", "")}, is_featured FROM olympiads
                {"WHERE is_featured = 1" if featured else ""}
                ORDER BY is_featured DESC, mentions DESC, id LIMIT :limit""",
            {"limit": limit},
        )
    ids = [i["id"] for i in items]
    if ids:
        counts = {
            r["olympiad_id"]: r["cnt"]
            for r in await fetch_all(
                session,
                """SELECT olympiad_id, COUNT(*) AS cnt FROM olympiad_profiles
                   WHERE olympiad_id = ANY(:ids) GROUP BY olympiad_id""",
                {"ids": ids},
            )
        }
        for item in items:
            item["profiles"] = counts.get(item["id"], 0)
    return {"count": len(items), "items": items}


async def olympiad_profiles(session: AsyncSession, olympiad_id: int) -> dict[str, Any]:
    olympiad = await fetch_one(
        session,
        f"SELECT {OLYMPIAD_FIELDS} FROM olympiads o WHERE o.id = :id",
        {"id": olympiad_id},
    )
    if not olympiad:
        raise HTTPException(status_code=404, detail="Олимпиада не найдена")
    items = await fetch_all(
        session,
        """SELECT id, name, mentions, bvi_count, sto_count, uni_count
           FROM olympiad_profiles WHERE olympiad_id = :id
           ORDER BY mentions DESC, name""",
        {"id": olympiad_id},
    )
    unassigned = await scalar(
        session,
        """SELECT COUNT(*) FROM benefit_olympiads
           WHERE olympiad_id = :id AND profile_id IS NULL""",
        {"id": olympiad_id},
    )
    return {
        "olympiad": olympiad,
        "count": len(items),
        "items": items,
        "without_profile": unassigned,
    }
