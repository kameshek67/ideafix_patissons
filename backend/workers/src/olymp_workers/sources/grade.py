"""Автопроверка разбора: оценка green / yellow / red и причины простыми словами.

green — можно принимать почти не глядя: цитаты найдены в тексте (≥98%), олимпиады сопоставлены
с базой (≥90%), коды направлений есть у вуза (≥90%), ранее принятые строки не пропадают, записей
не меньше 10. yellow — что-то из этого слабее, но цитаты ≥90%. red — цитаты <90% или ошибка.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from olymp_domain.extraction import ExtractionFile
from olymp_domain.textutils import OlympiadMatcher, squash

from olymp_workers.eval_extract import RE_CODE, pick_university

from .pipeline import JobResult

QUOTES_GREEN = 0.98
QUOTES_YELLOW = 0.90
OLYMPIADS_GREEN = 0.90
CODES_GREEN = 0.90
MIN_RECORDS = 10
ANY_CODE = "*"


@dataclass(frozen=True)
class Grade:
    grade: str
    reasons: list[str]


def percent(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def olympiad_matcher(conn: psycopg.Connection[Any]) -> OlympiadMatcher:
    matcher = OlympiadMatcher()
    for olympiad_id, alias in conn.execute("SELECT olympiad_id, alias FROM olympiad_aliases"):
        matcher.add(olympiad_id, alias, is_generic=len(squash(alias)) < 16)
    return matcher


def olympiads_matched(
    conn: psycopg.Connection[Any], files: list[ExtractionFile]
) -> tuple[int, int]:
    """(сопоставлено с олимпиадами базы, всего записей)."""
    matcher = olympiad_matcher(conn)
    total = matched = 0
    for file in files:
        for rec in file.records:
            total += 1
            if matcher.exact(rec.olympiad) or matcher.find(rec.olympiad):
                matched += 1
    return matched, total


def codes_existing(
    conn: psycopg.Connection[Any], files: list[ExtractionFile]
) -> tuple[int, int, bool]:
    """(записей с кодом, который есть у вуза или «*», всего записей, вуз найден в базе)."""
    total = ok = 0
    known = True
    for file in files:
        found = pick_university(conn, file.document.university)
        codes: set[str] = set()
        if found is None:
            known = False
        else:
            for code, direction in conn.execute(
                "SELECT code, faculty_or_direction FROM programs WHERE university_id = %s",
                (found[0],),
            ):
                codes.update(RE_CODE.findall(f"{code or ''} {direction or ''}"))
        for rec in file.records:
            total += 1
            if rec.program_code == ANY_CODE or rec.program_code in codes:
                ok += 1
    return ok, total, known


def grade_job(conn: psycopg.Connection[Any], result: JobResult) -> Grade:
    """Оценка готового разбора; причины перечисляют всё, что слабее нормы."""
    records = result.records
    checked, found = result.quotes_checked, result.quotes_found
    quotes = found / checked if checked else 0.0
    reasons: list[str] = []
    if quotes < QUOTES_GREEN:
        reasons.append(f"цитат найдено {percent(found, checked)}% (нужно от 98%)")
    matched, total = olympiads_matched(conn, result.files)
    if total and matched / total < OLYMPIADS_GREEN:
        reasons.append(f"олимпиад сопоставлено {percent(matched, total)}% (нужно от 90%)")
    ok, total_codes, known = codes_existing(conn, result.files)
    if not known:
        reasons.append("вуза нет в базе: коды направлений проверить не с чем")
    elif total_codes and ok / total_codes < CODES_GREEN:
        reasons.append(f"кодов направлений у вуза нашлось {percent(ok, total_codes)}%")
    removed = int(result.diff.get("removed") or 0)
    if removed:
        reasons.append(f"пропадёт ранее принятых строк: {removed}")
    if records < MIN_RECORDS:
        reasons.append(f"записей мало: {records} (нужно от {MIN_RECORDS})")
    if not reasons:
        return Grade("green", [])
    if quotes >= QUOTES_YELLOW and records:
        return Grade("yellow", reasons)
    return Grade("red", reasons)
