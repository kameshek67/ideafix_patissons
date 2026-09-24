# -*- coding: utf-8 -*-
"""
REST API сервиса «Олимпиада → ВУЗ».

Запуск:
    uvicorn main:app --reload --port 8000

Эндпоинты:
    GET /api/health
    GET /api/stats
    GET /api/regions
    GET /api/universities
    GET /api/programs?university_id=&q=
    GET /api/olympiads?q=&featured=          — автокомплит
    GET /api/search/by-program?program_id=   — «ищу олимпиады под вуз»
    GET /api/search/by-olympiad?q=           — обратный поиск «куда поступить»
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import db
from textutils import squash

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.environ.get("FRONTEND_DIR", os.path.join(HERE, "..", "frontend"))

BENEFIT_ORDER = ["БВИ", "100 баллов", "Особое право (БВИ/100)", "Фаст-трек", "ИД (доп. баллы)"]

app = FastAPI(
    title="Олимпиада → ВУЗ",
    version="1.0.0",
    description="Двусторонний поиск льгот БВИ и 100 баллов по олимпиадам школьников",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ==========================================================================
#  вспомогательное
# ==========================================================================

BENEFIT_FIELDS = """
    b.id, b.benefit_type, b.raw_conditions_text, b.layer, b.olympiad_profile,
    b.olympiad_subject, b.level, b.winner_role, b.grade, b.confirm_subject,
    b.min_ege, b.award_subject, b.years, b.note, b.source_title, b.source_url, b.source_sheet
"""


def serialize_benefit(row: Dict[str, Any], olympiads: Optional[List[Dict]] = None) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "benefit_type": row["benefit_type"],
        "layer": row["layer"],
        # строка выведена из правила «любая олимпиада перечня по профилю X»
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


def olympiads_for_benefits(benefit_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    if not benefit_ids:
        return {}
    out: Dict[int, List[Dict[str, Any]]] = {}
    chunk = 400
    for start in range(0, len(benefit_ids), chunk):
        part = benefit_ids[start:start + chunk]
        placeholders = ",".join("?" * len(part))
        rows = db.query(
            f"""SELECT bo.benefit_id, o.id, o.short_name, o.canonical_name, o.kind
                FROM benefit_olympiads bo JOIN olympiads o ON o.id = bo.olympiad_id
                WHERE bo.benefit_id IN ({placeholders})
                ORDER BY o.mentions DESC""",
            part,
        )
        for row in rows:
            out.setdefault(row["benefit_id"], []).append({
                "id": row["id"],
                "short_name": row["short_name"],
                "canonical_name": row["canonical_name"],
                "kind": row["kind"],
            })
    return out


def resolve_olympiads(q: str, limit: int = 12) -> List[Dict[str, Any]]:
    """Находит олимпиады по свободному вводу: «вышка», «всош», «покори воробьевы»."""
    key = squash(q)
    if len(key) < 2:
        return []
    rows = db.query(
        """SELECT DISTINCT o.id, o.canonical_name, o.short_name, o.kind, o.mentions,
                  o.bvi_count, o.sto_count, o.uni_count,
                  MIN(CASE
                        WHEN a.squash_alias = ? THEN 0
                        WHEN a.squash_alias LIKE ? THEN 1
                        WHEN instr(a.squash_alias, ?) > 0 THEN 2
                        ELSE 3 END) AS rank
           FROM olympiads o JOIN olympiad_aliases a ON a.olympiad_id = o.id
           WHERE a.squash_alias = ? OR a.squash_alias LIKE ? OR instr(a.squash_alias, ?) > 0
                 OR (length(a.squash_alias) >= 4 AND instr(?, a.squash_alias) > 0)
           GROUP BY o.id
           ORDER BY rank ASC, o.mentions DESC
           LIMIT ?""",
        (key, key + "%", key, key, key + "%", key, key, limit),
    )
    return rows


# ==========================================================================
#  справочники
# ==========================================================================


@app.get("/api/health")
def health() -> Dict[str, Any]:
    try:
        universities = db.scalar("SELECT COUNT(*) FROM universities")
    except Exception as exc:  # база ещё не построена
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)
    return {"status": "ok", "universities": universities, "db": db.db_path(),
            "fts": db.fts_enabled()}


@app.get("/api/stats")
def stats() -> Dict[str, Any]:
    meta = {row["key"]: row["value"] for row in db.query("SELECT key, value FROM meta")}
    by_type = db.query(
        "SELECT benefit_type, COUNT(*) AS cnt FROM benefits WHERE layer <> 'raw'"
        " GROUP BY benefit_type"
    )
    by_university = db.query(
        """SELECT u.id, u.name, u.short_name, u.region, u.city, u.region_group,
                  COUNT(DISTINCT p.id) AS programs,
                  SUM(CASE WHEN b.benefit_type = 'БВИ' THEN 1 ELSE 0 END) AS bvi,
                  SUM(CASE WHEN b.benefit_type = '100 баллов' THEN 1 ELSE 0 END) AS sto,
                  COUNT(b.id) AS benefits
           FROM universities u
           LEFT JOIN programs p ON p.university_id = u.id
           LEFT JOIN benefits b ON b.program_id = p.id AND b.layer <> 'raw'
           GROUP BY u.id ORDER BY benefits DESC"""
    )
    top_olympiads = db.query(
        """SELECT id, short_name, canonical_name, mentions, bvi_count, sto_count, uni_count
           FROM olympiads ORDER BY mentions DESC LIMIT 15"""
    )
    sheets = db.query(
        "SELECT sheet, rows_read, rows_ingested, benefits, comment FROM ingest_log ORDER BY id"
    )
    return {
        "totals": {
            "universities": int(meta.get("universities", 0)),
            "programs": int(meta.get("programs", 0)),
            "benefits": int(meta.get("benefits", 0)),
            "bvi": int(meta.get("benefits_bvi", 0)),
            "sto": int(meta.get("benefits_sto", 0)),
            "olympiads": int(meta.get("olympiads", 0)),
            "profiles": int(meta.get("profiles", 0)),
            "links": int(meta.get("links", 0)),
            "keywords": int(meta.get("keywords", 0)),
            "rows": int(meta.get("benefits_rows", 0)),
            "derived": int(meta.get("benefits_derived", 0)),
            "notes": int(meta.get("benefits_notes", 0)),
        },
        "source_file": meta.get("source_file", ""),
        "built_at": meta.get("built_at", ""),
        "benefit_types": {row["benefit_type"]: row["cnt"] for row in by_type},
        "universities": by_university,
        "top_olympiads": top_olympiads,
        "sheets": sheets,
    }


@app.get("/api/regions")
def regions() -> Dict[str, Any]:
    rows = db.query(
        """SELECT region_group, region, COUNT(*) AS universities
           FROM universities GROUP BY region_group, region ORDER BY region_group, region"""
    )
    groups: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        group = groups.setdefault(row["region_group"], {"name": row["region_group"],
                                                        "universities": 0, "regions": []})
        group["universities"] += row["universities"]
        group["regions"].append(row["region"])
    order = {"Москва": 0, "Санкт-Петербург": 1, "Регионы": 2}
    return {"items": sorted(groups.values(), key=lambda g: order.get(g["name"], 9))}


@app.get("/api/universities")
def universities(
    region: Optional[str] = Query(None, description="Москва | Санкт-Петербург | Регионы"),
    q: Optional[str] = None,
) -> Dict[str, Any]:
    sql = """SELECT u.id, u.name, u.short_name, u.region, u.city, u.note, u.region_group,
                    COUNT(DISTINCT p.id) AS programs,
                    SUM(CASE WHEN b.benefit_type = 'БВИ' THEN 1 ELSE 0 END) AS bvi,
                    SUM(CASE WHEN b.benefit_type = '100 баллов' THEN 1 ELSE 0 END) AS sto,
                    COUNT(b.id) AS benefits
             FROM universities u
             LEFT JOIN programs p ON p.university_id = u.id
             LEFT JOIN benefits b ON b.program_id = p.id AND b.layer <> 'raw'"""
    where, params = [], []
    if region and region != "Все":
        where.append("u.region_group = ?")
        params.append(region)
    if q:
        where.append("(u.name LIKE ? OR u.short_name LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY u.id ORDER BY benefits DESC, u.name"
    items = db.query(sql, params)
    return {"count": len(items), "items": items,
            "regions": [r["name"] for r in regions()["items"]]}


@app.get("/api/programs")
def programs(
    university_id: Optional[int] = None,
    q: Optional[str] = None,
    limit: int = Query(500, le=2000),
) -> Dict[str, Any]:
    sql = f"""SELECT p.id, p.university_id, p.faculty_or_direction, p.profile_name, p.code,
                     p.note, p.source_url, p.source_sheet, u.name AS university,
                     u.short_name AS university_short, u.region, u.region_group,
                     SUM(CASE WHEN b.benefit_type = 'БВИ' THEN 1 ELSE 0 END) AS bvi,
                     SUM(CASE WHEN b.benefit_type = '100 баллов' THEN 1 ELSE 0 END) AS sto,
                     COUNT(b.id) AS benefits
              FROM programs p
              JOIN universities u ON u.id = p.university_id
              LEFT JOIN benefits b ON b.program_id = p.id AND b.layer <> 'raw'"""
    where, params = [], []
    if university_id:
        where.append("p.university_id = ?")
        params.append(university_id)
    if q:
        where.append("(p.faculty_or_direction LIKE ? OR p.profile_name LIKE ? OR p.code LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY p.id ORDER BY p.sort_order, p.faculty_or_direction LIMIT ?"
    params.append(limit)
    items = db.query(sql, params)
    return {"count": len(items), "items": items}


@app.get("/api/olympiads")
def olympiads(
    q: Optional[str] = None,
    featured: bool = False,
    limit: int = Query(20, le=200),
) -> Dict[str, Any]:
    if q:
        items = resolve_olympiads(q, limit)
    else:
        sql = """SELECT id, canonical_name, short_name, kind, mentions, bvi_count, sto_count,
                        uni_count, is_featured
                 FROM olympiads"""
        if featured:
            sql += " WHERE is_featured = 1"
        sql += " ORDER BY is_featured DESC, mentions DESC LIMIT ?"
        items = db.query(sql, (limit,))
    ids = [i["id"] for i in items]
    if ids:
        placeholders = ",".join("?" * len(ids))
        counts = {r["olympiad_id"]: r["cnt"] for r in db.query(
            f"""SELECT olympiad_id, COUNT(*) AS cnt FROM olympiad_profiles
                WHERE olympiad_id IN ({placeholders}) GROUP BY olympiad_id""", ids)}
        for item in items:
            item["profiles"] = counts.get(item["id"], 0)
    return {"count": len(items), "items": items}


@app.get("/api/olympiads/{olympiad_id}/profiles")
def olympiad_profiles(olympiad_id: int) -> Dict[str, Any]:
    """Профили олимпиады: у НТО их 42, и льгота даётся за пару «олимпиада + профиль»."""
    olympiad = db.query_one(
        """SELECT id, canonical_name, short_name, kind, mentions, bvi_count, sto_count, uni_count
           FROM olympiads WHERE id = ?""", (olympiad_id,))
    if not olympiad:
        raise HTTPException(status_code=404, detail="Олимпиада не найдена")
    items = db.query(
        """SELECT id, name, mentions, bvi_count, sto_count, uni_count
           FROM olympiad_profiles WHERE olympiad_id = ?
           ORDER BY mentions DESC, name""", (olympiad_id,))
    unassigned = db.scalar(
        """SELECT COUNT(*) FROM benefit_olympiads
           WHERE olympiad_id = ? AND profile_id IS NULL""", (olympiad_id,))
    return {"olympiad": olympiad, "count": len(items), "items": items,
            "without_profile": unassigned}


# ==========================================================================
#  сценарий 1: «ищу олимпиады под ВУЗ»
# ==========================================================================


@app.get("/api/search/by-program")
def search_by_program(program_id: int) -> Dict[str, Any]:
    program = db.query_one(
        """SELECT p.id, p.faculty_or_direction, p.profile_name, p.code, p.note,
                  p.source_title, p.source_url, p.source_sheet,
                  u.id AS university_id, u.name AS university,
                  u.short_name AS university_short, u.region, u.city,
                  u.note AS university_note, u.site_url, u.docs_url, u.docs_title,
                  u.region_group
           FROM programs p JOIN universities u ON u.id = p.university_id
           WHERE p.id = ?""",
        (program_id,),
    )
    if not program:
        raise HTTPException(status_code=404, detail="Направление не найдено")

    rows = db.query(
        f"""SELECT {BENEFIT_FIELDS} FROM benefits b
            WHERE b.program_id = ? AND b.layer <> 'raw'
            ORDER BY CASE b.benefit_type
                        WHEN 'БВИ' THEN 0 WHEN '100 баллов' THEN 1
                        WHEN 'Особое право (БВИ/100)' THEN 2 WHEN 'Фаст-трек' THEN 3
                        ELSE 4 END,
                     b.level, b.id""",
        (program_id,),
    )
    links = olympiads_for_benefits([r["id"] for r in rows])

    groups: Dict[str, Dict[str, Any]] = {}
    notes: List[Dict[str, str]] = []
    seen_notes: set = set()
    olympiad_index: Dict[int, Dict[str, Any]] = {}

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
        group = groups.setdefault(row["benefit_type"],
                                  {"type": row["benefit_type"], "rows": [], "count": 0})
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

    # Источники показываем в порядке надёжности: сначала стабильная страница раздела
    # (её адрес живёт годами), потом конкретные файлы, найденные на ней.
    sources: List[Dict[str, Any]] = []
    if program["docs_url"]:
        sources.append({"title": program["docs_title"] or "Документы приёмной комиссии",
                        "url": program["docs_url"], "kind": "page", "types": []})
    for row in db.query(
        """SELECT title, url, checked_at FROM university_documents
           WHERE university_id = ? ORDER BY id LIMIT 4""", (program["university_id"],)):
        sources.append({"title": row["title"], "url": row["url"], "kind": "file",
                        "checked_at": row["checked_at"], "types": []})
    if not sources:
        seen_urls: Dict[str, Dict[str, Any]] = {}
        for row in db.query(
            """SELECT source_title, source_url, GROUP_CONCAT(DISTINCT benefit_type) AS types
               FROM benefits WHERE program_id = ? AND source_url <> '' AND layer <> 'raw'
               GROUP BY source_url""", (program_id,)):
            seen_urls[row["source_url"]] = {"title": row["source_title"], "url": row["source_url"],
                                            "kind": "file", "types": (row["types"] or "").split(",")}
        if program["source_url"] and program["source_url"] not in seen_urls:
            seen_urls[program["source_url"]] = {"title": program["source_title"], "kind": "file",
                                                "url": program["source_url"], "types": []}
        sources = list(seen_urls.values())
    return {
        "program": {k: program[k] for k in
                    ("id", "faculty_or_direction", "profile_name", "code", "note",
                     "source_title", "source_url", "source_sheet")},
        "university": {"id": program["university_id"], "name": program["university"],
                       "short_name": program["university_short"], "region": program["region"],
                       "city": program["city"], "note": program["university_note"],
                       "site_url": program["site_url"], "docs_url": program["docs_url"],
                       "docs_title": program["docs_title"],
                       "region_group": program["region_group"]},
        "groups": ordered,
        "notes": notes,
        "olympiads": olympiad_list,
        "sources": sources,
        "total_benefits": sum(g["count"] for g in ordered),
    }


# ==========================================================================
#  сценарий 2: обратный поиск «куда поступить с моей олимпиадой»
# ==========================================================================


@app.get("/api/search/by-olympiad")
def search_by_olympiad(
    q: str = Query(..., min_length=2, description="Название олимпиады или её часть"),
    olympiad_id: Optional[int] = None,
    profile_id: Optional[int] = None,
    university_id: Optional[int] = None,
    region: Optional[str] = None,
    benefit_type: Optional[str] = None,
    limit: int = Query(400, le=2000),
) -> Dict[str, Any]:
    matched = ([db.query_one("""SELECT id, canonical_name, short_name, kind, mentions,
                                       bvi_count, sto_count, uni_count
                                FROM olympiads WHERE id = ?""", (olympiad_id,))]
               if olympiad_id else resolve_olympiads(q))
    matched = [m for m in matched if m]

    if not matched:
        return {"query": q, "matched_olympiads": [], "results": [], "total_programs": 0,
                "total_universities": 0, "profiles": [], "fallback": fts_fallback(q, limit)}

    ids = [m["id"] for m in matched[:5]]
    placeholders = ",".join("?" * len(ids))

    # профили выбранной олимпиады — для чипов-фильтров на фронте
    profiles = db.query(
        f"""SELECT id, olympiad_id, name, mentions, bvi_count, sto_count, uni_count
            FROM olympiad_profiles WHERE olympiad_id IN ({placeholders})
            ORDER BY mentions DESC, name""", ids)
    without_profile = db.scalar(
        f"""SELECT COUNT(*) FROM benefit_olympiads
            WHERE olympiad_id IN ({placeholders}) AND profile_id IS NULL""", ids)

    params: List[Any] = list(ids)
    where = [f"bo.olympiad_id IN ({placeholders})", "b.layer <> 'raw'"]
    if profile_id:
        where.append("bo.profile_id = ?")
        params.append(profile_id)
    if university_id:
        where.append("u.id = ?")
        params.append(university_id)
    if region and region != "Все":
        where.append("u.region_group = ?")
        params.append(region)
    if benefit_type and benefit_type != "Все":
        where.append("b.benefit_type = ?")
        params.append(benefit_type)

    # точные итоги считаем агрегатом — выдача ниже ограничена лимитом
    totals = db.query(
        f"""SELECT u.id AS university_id, COUNT(DISTINCT p.id) AS programs_total,
                   SUM(CASE WHEN b.benefit_type = 'БВИ' THEN 1 ELSE 0 END) AS bvi,
                   SUM(CASE WHEN b.benefit_type = '100 баллов' THEN 1 ELSE 0 END) AS sto,
                   SUM(CASE WHEN b.benefit_type NOT IN ('БВИ', '100 баллов') THEN 1 ELSE 0 END) AS other
            FROM benefit_olympiads bo
            JOIN benefits b ON b.id = bo.benefit_id
            JOIN programs p ON p.id = b.program_id
            JOIN universities u ON u.id = p.university_id
            WHERE {' AND '.join(where)}
            GROUP BY u.id""",
        params,
    )
    totals_by_university = {row["university_id"]: row for row in totals}
    programs_total = sum(row["programs_total"] for row in totals)

    rows = db.query(
        f"""SELECT {BENEFIT_FIELDS},
                   p.id AS program_id, p.faculty_or_direction, p.profile_name, p.code,
                   p.note AS program_note, p.source_url AS program_url,
                   p.source_title AS program_source_title,
                   u.id AS university_id, u.name AS university, u.short_name AS university_short,
                   u.region, u.city, u.note AS university_note, u.site_url,
                   u.docs_url, u.docs_title, u.region_group,
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
            WHERE {' AND '.join(where)}
            ORDER BY u.region_group, u.name, p.sort_order, p.id,
                     CASE b.benefit_type WHEN 'БВИ' THEN 0 WHEN '100 баллов' THEN 1 ELSE 2 END,
                     b.id
            LIMIT ?""",
        params + [limit * 15],
    )

    universities_map: Dict[int, Dict[str, Any]] = {}
    programs_seen: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        aggregate = totals_by_university.get(row["university_id"], {})
        uni = universities_map.setdefault(row["university_id"], {
            "university": {"id": row["university_id"], "name": row["university"],
                           "short_name": row["university_short"], "region": row["region"],
                           "city": row["city"], "note": row["university_note"],
                           "site_url": row["site_url"], "docs_url": row["docs_url"],
                           "docs_title": row["docs_title"],
                           "region_group": row["region_group"]},
            "programs": [],
            "programs_total": aggregate.get("programs_total", 0),
            "bvi": aggregate.get("bvi", 0),
            "sto": aggregate.get("sto", 0),
            "other": aggregate.get("other", 0),
        })
        program = programs_seen.get(row["program_id"])
        if program is None:
            if len(programs_seen) >= limit:
                continue
            program = {
                "program": {"id": row["program_id"],
                            "faculty_or_direction": row["faculty_or_direction"],
                            "profile_name": row["profile_name"], "code": row["code"],
                            "note": row["program_note"], "source_url": row["program_url"],
                            "source_title": row["program_source_title"]},
                "benefits": [], "types": [],
            }
            programs_seen[row["program_id"]] = program
            uni["programs"].append(program)
        benefit = serialize_benefit(row, [{"id": row["olympiad_id"],
                                           "short_name": row["olympiad_short"]}])
        benefit["matched"] = {"profile": row["matched_profile"],
                              "profile_id": row["matched_profile_id"],
                              "level": row["matched_level"],
                              "role": row["matched_role"], "via": row["matched_via"]}
        if not any(b["id"] == benefit["id"] for b in program["benefits"]):
            program["benefits"].append(benefit)
        if row["benefit_type"] not in program["types"]:
            program["types"].append(row["benefit_type"])

    # вузы, у которых все направления не влезли в лимит выдачи, всё равно показываем в списке
    for aggregate_university_id, aggregate in totals_by_university.items():
        if aggregate_university_id in universities_map:
            continue
        info = db.query_one(
            "SELECT id, name, short_name, region, city, note, region_group"
            " FROM universities WHERE id = ?", (aggregate_university_id,))
        if info:
            universities_map[aggregate_university_id] = {
                "university": info, "programs": [],
                "programs_total": aggregate["programs_total"], "bvi": aggregate["bvi"],
                "sto": aggregate["sto"], "other": aggregate["other"],
            }

    results = sorted(universities_map.values(),
                     key=lambda u: (-(u["bvi"] + u["sto"] + u["other"]), u["university"]["name"]))
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


def fts_fallback(q: str, limit: int) -> List[Dict[str, Any]]:
    """Если олимпиада не опознана — полнотекстовый поиск по условиям."""
    if not db.fts_enabled():
        like = f"%{q}%"
        return db.query(
            """SELECT b.id, b.benefit_type, b.raw_conditions_text AS text,
                      p.id AS program_id, p.faculty_or_direction, u.name AS university
               FROM benefits b JOIN programs p ON p.id = b.program_id
               JOIN universities u ON u.id = p.university_id
               WHERE b.raw_conditions_text LIKE ? LIMIT ?""",
            (like, min(limit, 50)),
        )
    tokens = [t for t in squash_tokens(q) if t]
    if not tokens:
        return []
    match = " AND ".join(f'"{t}"*' for t in tokens)
    try:
        return db.query(
            """SELECT si.rowid AS id, b.benefit_type, b.raw_conditions_text AS text,
                      p.id AS program_id, p.faculty_or_direction, u.name AS university
               FROM search_index si
               JOIN benefits b ON b.id = si.rowid
               JOIN programs p ON p.id = b.program_id
               JOIN universities u ON u.id = p.university_id
               WHERE search_index MATCH ? LIMIT ?""",
            (match, min(limit, 50)),
        )
    except Exception:
        return []


def squash_tokens(q: str) -> List[str]:
    return [t.strip('"').lower() for t in q.replace('"', " ").split() if len(t) >= 2]


# ==========================================================================
#  статика фронтенда (одноконтейнерный режим)
# ==========================================================================

if os.path.isdir(FRONTEND_DIR):
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
