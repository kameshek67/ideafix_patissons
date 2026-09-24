# -*- coding: utf-8 -*-
"""
Парсер XLSX «Олимпиады: БВИ и 100 баллов» -> нормализованная SQLite.

Запуск:
    python ingest_data.py --xlsx ../data/Olimpiady_BVI_100ballov.xlsx --db ../data/bvi_database.db

Что делает:
  1. Читает лист «База» (сводные правила по вузам и направлениям).
  2. Читает 15 подробных листов (ВШЭ, РЭУ, МИФИ, Бауманка, Финуниверситет,
     КФУ, УрФУ, ЦУ, Иннополис, Пирогова, ...) — каждый своим адаптером.
  3. Схлопывает ~450 грязных написаний названий олимпиад в канонический
     справочник (olympiads + olympiad_aliases).
  4. Строит связи «льгота ↔ олимпиада» (benefit_olympiads) — по колонке
     подробных листов и по тексту условий из «Базы».
  5. Вытаскивает ключевые слова (уровень, победитель/призёр, класс, порог ЕГЭ,
     предметы) в benefit_keywords и наполняет полнотекстовый индекс FTS5.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

import openpyxl

from olympiad_seeds import JUNK_KEYS, SEEDS, Seed
from university_pages import PAGES
from textutils import (
    OlympiadMatcher,
    ProfileIndex,
    clean_name,
    clean_profile,
    clean_text,
    extract_codes,
    find_ege_thresholds,
    find_grades,
    find_levels,
    find_roles,
    find_subjects,
    has_glued_digits,
    norm_level,
    norm_role,
    parse_enumeration,
    parse_profile_rules,
    short_from_quotes,
    split_source,
    squash,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_XLSX = os.path.join(HERE, "..", "data", "Olimpiady_BVI_100ballov.xlsx")
DEFAULT_DB = os.path.join(HERE, "..", "data", "bvi_database.db")
SOURCES_CACHE = os.environ.get(
    "SOURCES_CACHE", os.path.join(HERE, "..", "data", "university_documents.json"))

BVI = "БВИ"
STO = "100 баллов"
SPECIAL = "Особое право (БВИ/100)"
FASTTRACK = "Фаст-трек"
EXTRA_POINTS = "ИД (доп. баллы)"

SHEET_BASE = "База"

# Приложение 2 «Особые права… НИУ ВШЭ (Москва) 2026» — проверенная рабочая ссылка
HSE_SOURCE = ("Приложение 2 «Особые права при приёме… НИУ ВШЭ (г. Москва) 2026» — "
              "https://ba.hse.ru/mirror/pubs/share/1170753560")

# лист -> индекс колонки с названием олимпиады (для сбора справочника)
OLYMPIAD_COLUMNS: Dict[str, int] = {
    "ВШЭ подробно": 3,
    "РЭУ подробно": 0,
    "ВШЭ филиалы подробно": 3,
    "МИФИ подробно": 1,
    "Бауманка подробно": 1,
    "Финуниверситет подробно": 0,
    "КФУ подробно": 0,
    "ЦУ фаст-трек": 1,
    "Иннополис подробно": 1,
    "Пирогова подробно": 2,
    "УрФУ +4 балла": 1,
    "ВШЭ международные": 1,
}

# В «Базе» регион у части вузов — федеральный округ; для таблиц нужен город.
CITY_HINTS = {
    "казанский": "Казань",
    "уральскийфедеральный": "Екатеринбург",
    "сибирскийфедеральный": "Красноярск",
    "новосибирский": "Новосибирск",
    "иннополис": "Иннополис",
    "мифифилиалы": "филиалы в регионах",
}
# Прямые документы приёмных комиссий: перекрывают ссылку из таблицы, если та ведёт
# на общую страницу. Ключ — подстрока названия вуза, внутри — тип льготы ('*' — любой).
# Все ссылки проверены запросом: 200 OK, Content-Type: application/pdf.
OFFICIAL_SOURCES: Dict[str, Dict[str, Tuple[str, str]]] = {
    "итмо": {
        "БВИ": ("Приложение 5: олимпиады РСОШ, дающие БВИ (2026)",
                "https://abit.itmo.ru/file_storage/file/pages/82/rsosh_bvi_2026.pdf"),
        "100 баллов": ("Приложение 5: олимпиады РСОШ на 100 баллов (2026)",
                       "https://abit.itmo.ru/file_storage/file/pages/82/rsosh_100_2026.pdf"),
        "*": ("Приложение 5: перечень олимпиад ИТМО (2026)",
              "https://abit.itmo.ru/file_storage/file/pages/82/rsosh_bvi_2026.pdf"),
    },
}

# Вузы, у которых в исходной таблице нет ни одной прямой ссылки: ведём на приёмную
# комиссию, чтобы из карточки всегда можно было дойти до первоисточника.
# Все адреса проверены запросом (200 OK) при сборке этой версии.
UNIVERSITY_SOURCES = {
    "казанский": ("Приёмная комиссия КФУ", "https://admissions.kpfu.ru/"),
    "пирогов": ("Приёмная комиссия РНИМУ им. Н.И. Пирогова", "https://rsmu.ru/"),
    "баумана": ("Приёмная комиссия МГТУ им. Н.Э. Баумана", "https://priem.bmstu.ru/"),
    "губкина": ("Приёмная комиссия РГУ нефти и газа им. И.М. Губкина", "https://priem.gubkin.ru/"),
}

UNIVERSITY_NOTES = {
    "мифифилиалы": "В источнике правила приёма даны сразу для всех филиалов НИЯУ МИФИ, "
                   "без разбивки по городам",
}

# сокращения предметов в таблицах УрФУ
URFU_SUBJECTS = {
    "а": "астрономия", "б": "биология", "г": "география", "и": "история",
    "ин": "иностранный язык", "ия": "иностранный язык", "инф": "информатика",
    "л": "литература", "м": "математика", "о": "обществознание",
    "ря": "русский язык", "т": "труд (технология)", "ф": "физика",
    "х": "химия", "э": "экология", "эк": "экономика",
}


def log(msg: str) -> None:
    print(msg, flush=True)


# ==========================================================================
#  справочник олимпиад
# ==========================================================================


@dataclass
class CanonicalOlympiad:
    short_name: str
    canonical_name: str
    kind: str = "rsosh"
    featured: bool = False
    aliases: Set[str] = field(default_factory=set)
    squash_keys: Set[str] = field(default_factory=set)
    mentions: int = 0
    db_id: int = 0


class OlympiadCatalog:
    """Схлопывает грязные варианты написания в канонические олимпиады."""

    def __init__(self) -> None:
        self.items: List[CanonicalOlympiad] = []
        self._by_seed: Dict[int, CanonicalOlympiad] = {}

    # -- сбор -------------------------------------------------------------
    def harvest(self, wb) -> Dict[str, Counter]:
        raw: Dict[str, Counter] = defaultdict(Counter)
        for sheet, col in OLYMPIAD_COLUMNS.items():
            if sheet not in wb.sheetnames:
                continue
            for row in wb[sheet].iter_rows(min_row=2, values_only=True):
                value = row[col] if col < len(row) else None
                name = clean_name(value)
                if not name:
                    continue
                key = squash(name)
                if len(key) < 6:
                    continue
                raw[key][name] += 1
        return raw

    def build(self, wb) -> None:
        raw = self.harvest(wb)
        totals = {key: sum(c.values()) for key, c in raw.items()}
        display = {key: self._best_display(c) for key, c in raw.items()}

        assigned: Dict[str, CanonicalOlympiad] = {}

        # 1) якоря из справочника
        for idx, seed in enumerate(SEEDS):
            item = CanonicalOlympiad(seed.short, seed.full, seed.kind, seed.featured)
            item.aliases.update(a for a in seed.aliases if a)
            item.aliases.add(seed.short.strip("«»"))
            item.aliases.add(seed.full)
            self._by_seed[idx] = item

        for key in sorted(raw, key=lambda k: -totals[k]):
            if key in JUNK_KEYS:
                continue
            seed_idx = self._match_seed(key)
            if seed_idx is None:
                continue
            item = self._by_seed[seed_idx]
            item.squash_keys.add(key)
            item.aliases.add(display[key])
            item.mentions += totals[key]
            assigned[key] = item

        # 2) оставшиеся ключи: склейка обрывков в более длинные названия
        leftovers = [k for k in raw if k not in assigned and k not in JUNK_KEYS]
        leftovers.sort(key=lambda k: len(k))
        own: Dict[str, CanonicalOlympiad] = {}
        for key in leftovers:
            parent = self._find_parent(key, raw, assigned, own, totals)
            if parent is not None:
                parent.squash_keys.add(key)
                parent.aliases.add(display[key])
                parent.mentions += totals[key]
                assigned[key] = parent
                continue
            if len(key) < 12:
                continue  # обрывок строки из PDF
            name = display[key]
            item = CanonicalOlympiad(
                short_name=short_from_quotes(name) or self._shorten(name),
                canonical_name=name,
            )
            item.squash_keys.add(key)
            item.aliases.add(name)
            item.mentions += totals[key]
            own[key] = item
            assigned[key] = item

        self.items = [i for i in self._by_seed.values() if i.squash_keys] + list(own.values())
        # длинные названия -> алиасы; уникальность по каноническому имени
        seen_names: Set[str] = set()
        for item in self.items:
            base = item.canonical_name
            n = 2
            while item.canonical_name in seen_names:
                item.canonical_name = f"{base} ({n})"
                n += 1
            seen_names.add(item.canonical_name)

    def add_international(self, wb) -> List[Tuple[CanonicalOlympiad, str]]:
        """Лист «ВШЭ международные»: международные олимпиады + краткие коды."""
        out: List[Tuple[CanonicalOlympiad, str]] = []
        if "ВШЭ международные" not in wb.sheetnames:
            return out
        for row in wb["ВШЭ международные"].iter_rows(min_row=2, values_only=True):
            name = clean_name(row[1] if len(row) > 1 else None)
            short = clean_text(row[2] if len(row) > 2 else None)
            subject = clean_text(row[3] if len(row) > 3 else None)
            if not name:
                continue
            item = self._lookup_by_key(squash(name))
            if item is None:
                item = CanonicalOlympiad(
                    short_name=short or self._shorten(name),
                    canonical_name=name,
                    kind="international",
                )
                item.squash_keys.add(squash(name))
                item.aliases.add(name)
                self.items.append(item)
            if short:
                item.aliases.add(short)
            item.kind = "international"
            out.append((item, subject))
        return out

    # -- внутреннее -------------------------------------------------------
    def _lookup_by_key(self, key: str) -> Optional[CanonicalOlympiad]:
        for item in self.items:
            if key in item.squash_keys:
                return item
        return None

    def _match_seed(self, key: str) -> Optional[int]:
        for idx, seed in enumerate(SEEDS):
            if any(bad in key for bad in seed.exclude):
                continue
            for pattern_set in seed.patterns:
                if all(p in key for p in pattern_set):
                    return idx
        return None

    @staticmethod
    def _find_parent(
        key: str,
        raw: Dict[str, Counter],
        assigned: Dict[str, CanonicalOlympiad],
        own: Dict[str, CanonicalOlympiad],
        totals: Dict[str, int],
    ) -> Optional[CanonicalOlympiad]:
        """Обрывок «...школьников Уральского...» приклеиваем к полному названию."""
        if len(key) < 12:
            return None
        candidates: List[Tuple[int, CanonicalOlympiad]] = []
        for other, item in list(assigned.items()) + [(k, v) for k, v in own.items()]:
            if other == key or len(other) <= len(key):
                continue
            if key in other:
                candidates.append((totals.get(other, 0), item))
        if not candidates:
            return None
        candidates.sort(key=lambda c: -c[0])
        return candidates[0][1]

    @staticmethod
    def _best_display(counter: Counter) -> str:
        def score(item: Tuple[str, int]) -> Tuple[int, int, int]:
            name, cnt = item
            return (0 if has_glued_digits(name) else 1, cnt, len(name))

        return max(counter.items(), key=score)[0]

    @staticmethod
    def _shorten(name: str) -> str:
        s = clean_text(name)
        if len(s) <= 46:
            return s
        cut = s[:46].rsplit(" ", 1)[0]
        return cut + "…"


# ==========================================================================
#  реестр программ (склейка «Базы» и подробных листов)
# ==========================================================================

RE_GROUP = re.compile(r"групп[аы]\s*№?\s*(\d+)", re.IGNORECASE)
RE_SUBJ_IN_QUOTES = re.compile(r"предмету\s*[«\"]([^»\"]+)[»\"]", re.IGNORECASE)


def program_keys(name: str, code: str = "", profile: str = "") -> List[str]:
    """Ключи, по которым строка «Базы» и строка подробного листа считаются одной программой."""
    keys: List[str] = []
    text = clean_text(name)
    codes = extract_codes(text) or ([code] if code else [])
    codes = sorted({c for c in codes if c})
    name_wo_codes = squash(re.sub(r"\d{2}\.\d{2}\.\d{2}", " ", text))
    profile_key = squash(profile)

    if name_wo_codes and codes:
        keys.append("nc:" + name_wo_codes + "|" + ",".join(codes))
    if name_wo_codes and profile_key:
        keys.append("np:" + name_wo_codes + "|" + profile_key)
    if name_wo_codes and len(name_wo_codes) >= 4:
        keys.append("n:" + name_wo_codes)
    m = RE_GROUP.search(text)
    if m:
        keys.append("g:" + m.group(1))
    m = RE_SUBJ_IN_QUOTES.search(text)
    if m:
        keys.append("s:" + squash(m.group(1)))
    if codes:
        keys.append("c:" + ",".join(codes))
    return keys


class ProgramRegistry:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._keys: Dict[Tuple[int, str], int] = {}
        self._order: Dict[int, int] = defaultdict(int)

    def get_or_create(
        self,
        university_id: int,
        name: str,
        code: str = "",
        profile: str = "",
        note: str = "",
        source_url: str = "",
        source_sheet: str = "",
    ) -> int:
        name = clean_text(name) or "Без названия"
        keys = program_keys(name, code, profile)
        for key in keys:
            pid = self._keys.get((university_id, key))
            if pid is not None:
                self._enrich(pid, note, source_url)
                return pid

        codes = extract_codes(name) or ([code] if code else [])
        self._order[university_id] += 1
        source_title, source_link = split_source(source_url)
        cur = self.conn.execute(
            """INSERT INTO programs
               (university_id, faculty_or_direction, profile_name, code, note, source_title,
                source_url, source_sheet, sort_order)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (university_id, name, clean_text(profile), ", ".join(sorted(set(codes))),
             clean_text(note), source_title, source_link, source_sheet,
             self._order[university_id]),
        )
        pid = int(cur.lastrowid)
        for key in keys:
            self._keys.setdefault((university_id, key), pid)
        return pid

    def _enrich(self, program_id: int, note: str, source_url: str) -> None:
        """Подробный лист может дать источник/примечание там, где «База» промолчала."""
        if not note and not source_url:
            return
        row = self.conn.execute(
            "SELECT note, source_title, source_url FROM programs WHERE id=?", (program_id,)
        ).fetchone()
        title, link = split_source(source_url)
        self.conn.execute(
            "UPDATE programs SET note=?, source_title=?, source_url=? WHERE id=?",
            (row[0] or clean_text(note), row[1] or title, row[2] or link, program_id),
        )


# ==========================================================================
#  строки подробных листов
# ==========================================================================


@dataclass
class DetailRow:
    university: str
    program_name: str
    benefit_type: str
    conditions: str
    code: str = ""
    profile_name: str = ""
    olympiad_name: str = ""
    olympiad_id: int = 0          # если олимпиада уже определена — не ищем по названию
    olympiad_profile: str = ""
    olympiad_subject: str = ""
    level: str = ""
    winner_role: str = ""
    grade: str = ""
    confirm_subject: str = ""
    min_ege: str = ""
    award_subject: str = ""
    years: str = ""
    note: str = ""
    source_url: str = ""


def cell(row: Sequence, idx: int) -> str:
    return clean_text(row[idx]) if idx < len(row) else ""


def join_parts(*parts: str) -> str:
    return " · ".join(p for p in (clean_text(x) for x in parts) if p)


# --------------------------------------------------------------------------
#  адаптеры листов
# --------------------------------------------------------------------------


def adapt_hse(rows: Iterable[Sequence]) -> Iterator[DetailRow]:
    url = HSE_SOURCE
    for row in rows:
        program = cell(row, 1)
        benefit = cell(row, 8)
        olympiad = clean_name(cell(row, 3))
        if not program or benefit not in (BVI, STO) or not olympiad:
            continue
        profile = cell(row, 4)
        role = norm_role(cell(row, 10))
        grade = cell(row, 11)
        yield DetailRow(
            university="НИУ ВШЭ (Москва)",
            program_name=program,
            code=cell(row, 2),
            benefit_type=benefit,
            olympiad_name=olympiad,
            olympiad_profile=profile,
            olympiad_subject=cell(row, 5),
            winner_role=role,
            grade=grade,
            confirm_subject=cell(row, 6),
            min_ege=cell(row, 7),
            award_subject=cell(row, 9),
            conditions=join_parts(olympiad, f"профиль: {profile}" if profile else "", role, grade),
            source_url=url,
        )


def adapt_hse_branches(rows: Iterable[Sequence]) -> Iterator[DetailRow]:
    campus_map = {
        "Санкт-Петербург": "НИУ ВШЭ — Санкт-Петербург",
        "Нижний Новгород": "НИУ ВШЭ — Нижний Новгород",
        "Пермь": "НИУ ВШЭ — Пермь",
    }
    for row in rows:
        campus = cell(row, 0)
        university = campus_map.get(campus)
        program = cell(row, 2)
        benefit = cell(row, 8)
        olympiad = clean_name(cell(row, 3))
        if not university or not program or benefit not in (BVI, STO) or not olympiad:
            continue
        direction = cell(row, 1)
        profile = cell(row, 4)
        role = norm_role(cell(row, 10))
        grade = cell(row, 11)
        yield DetailRow(
            university=university,
            program_name=program,
            code=", ".join(extract_codes(direction)),
            profile_name=re.sub(r"\d{2}\.\d{2}\.\d{2}", "", direction).strip(),
            benefit_type=benefit,
            olympiad_name=olympiad,
            olympiad_profile=profile,
            olympiad_subject=cell(row, 5),
            winner_role=role,
            grade=grade,
            confirm_subject=cell(row, 6),
            min_ege=cell(row, 7),
            award_subject=cell(row, 9),
            conditions=join_parts(olympiad, f"профиль: {profile}" if profile else "", role, grade),
        )


def adapt_hse_vsosh(rows: Iterable[Sequence]) -> Iterator[DetailRow]:
    vsosh = "Всероссийская олимпиада школьников (заключительный этап)"
    for row in rows:
        program = cell(row, 1)
        if not program:
            continue
        for idx, benefit in ((2, BVI), (3, STO)):
            subject = cell(row, idx)
            if not subject:
                continue
            yield DetailRow(
                university="НИУ ВШЭ (Москва)",
                program_name=program,
                benefit_type=benefit,
                olympiad_name=vsosh,
                olympiad_subject=subject,
                winner_role="победители и призёры",
                conditions=f"ВсОШ (заключительный этап), предмет: {subject}",
                note="Подтверждение ЕГЭ для ВсОШ не требуется",
            )


def adapt_rea(rows: Iterable[Sequence]) -> Iterator[DetailRow]:
    """РЭУ: 27 510 строк «олимпиада × год × предмет» -> агрегируем по годам и предметам."""
    url = "https://www.rea.ru/pk/entrant"
    agg: Dict[Tuple[str, str, str, str, str], Dict[str, Set[str]]] = {}
    for row in rows:
        olympiad = clean_name(cell(row, 0))
        benefit = cell(row, 2)
        direction = cell(row, 4)
        if not olympiad or benefit not in (BVI, STO) or not direction:
            continue
        key = (cell(row, 3), direction, olympiad, cell(row, 5), benefit)
        bucket = agg.setdefault(key, {"years": set(), "subjects": set(), "scores": set(), "profiles": set()})
        if cell(row, 1):
            bucket["years"].add(cell(row, 1))
        if cell(row, 7):
            bucket["subjects"].add(cell(row, 7))
        if cell(row, 8) and cell(row, 8) != "-":
            bucket["scores"].add(cell(row, 8))
        if cell(row, 6):
            bucket["profiles"].add(cell(row, 6))

    for (code, direction, olympiad, profile, benefit), bucket in agg.items():
        years = ", ".join(sorted(bucket["years"]))
        subjects = ", ".join(sorted(bucket["subjects"]))
        scores = ", ".join(sorted(bucket["scores"], key=lambda s: int(s) if s.isdigit() else 0))
        yield DetailRow(
            university="РЭУ им. Г.В. Плеханова",
            program_name=direction,
            code=code,
            benefit_type=benefit,
            olympiad_name=olympiad,
            olympiad_profile=profile,
            confirm_subject=subjects,
            min_ege=scores,
            years=years,
            conditions=join_parts(olympiad, f"профиль: {profile}" if profile else "",
                                  f"подтверждение ЕГЭ: {subjects}" if subjects else ""),
            source_url=url,
        )


def adapt_mephi(rows: Iterable[Sequence]) -> Iterator[DetailRow]:
    url = "https://admission.mephi.ru/admission/baccalaureate-and-specialty/specials/winners"
    for row in rows:
        campus = cell(row, 0)
        university = "НИЯУ МИФИ" if campus == "Москва" else "НИЯУ МИФИ — филиалы"
        olympiad = clean_name(cell(row, 1))
        if not olympiad:
            continue
        level = norm_level(cell(row, 2))
        subject = cell(row, 3)
        profile = cell(row, 4)
        for idx, benefit in ((5, BVI), (6, STO)):
            for code in extract_codes(cell(row, idx)):
                yield DetailRow(
                    university=university,
                    program_name=code,
                    code=code,
                    benefit_type=benefit,
                    olympiad_name=olympiad,
                    olympiad_profile=profile,
                    olympiad_subject=subject,
                    level=level,
                    winner_role="победители и призёры",
                    confirm_subject=subject,
                    min_ege="75",
                    conditions=join_parts(olympiad, f"профиль: {profile}" if profile else "",
                                          f"уровень {level}" if level else "",
                                          "победители и призёры"),
                    note="Подтверждение ЕГЭ ≥75 по предмету олимпиады",
                    source_url=url,
                )


def adapt_bauman(rows: Iterable[Sequence]) -> Iterator[DetailRow]:
    for row in rows:
        group = cell(row, 0)
        olympiad = clean_name(cell(row, 1))
        if not group or not olympiad:
            continue
        profile = cell(row, 2)
        subjects = cell(row, 3)
        level = norm_level(cell(row, 4))
        confirm = cell(row, 5)
        winners = cell(row, 6)
        prizers = cell(row, 7)
        base = dict(
            university="МГТУ им. Н.Э. Баумана",
            program_name=group,
            code=", ".join(extract_codes(group)),
            olympiad_name=olympiad,
            olympiad_profile=profile,
            olympiad_subject=subjects,
            level=level,
            confirm_subject=confirm,
            min_ege="75",
        )
        gives_winners = winners.startswith("Предоставляется")
        gives_prizers = prizers.startswith("Предоставляется")
        if gives_winners or gives_prizers:
            if gives_winners and gives_prizers:
                role = "победители и призёры"
            elif gives_winners:
                role = "только победители"
            else:
                role = "призёры"
            yield DetailRow(
                benefit_type=BVI,
                winner_role=role,
                conditions=join_parts(olympiad, f"профиль: {profile}" if profile else "",
                                      f"уровень {level}" if level else "", role),
                note=("БВИ только на программы кафедр секции" if "кафедр" in winners else
                      "Подтверждение ЕГЭ ≥75 по профильному предмету"),
                **base,
            )
        if gives_winners and not gives_prizers:
            yield DetailRow(
                benefit_type=STO,
                winner_role="призёры",
                conditions=join_parts(olympiad, f"профиль: {profile}" if profile else "",
                                      f"уровень {level}" if level else "",
                                      "призёры (БВИ не даётся) — 100 баллов по предмету олимпиады"),
                note="Призёрам олимпиад из списка «только победители» засчитывается 100 баллов",
                **base,
            )


def adapt_finuniver(rows: Iterable[Sequence]) -> Iterator[DetailRow]:
    url = "https://www.fa.ru/for-applicants/priyemka/sootvetstvie-profilej-olimpiad/"
    for row in rows:
        group = cell(row, 3)
        olympiad = clean_name(cell(row, 0))
        if not olympiad or not RE_GROUP.search(group):
            continue  # вторая строка-шапка
        subject = cell(row, 2)
        profile = cell(row, 1)
        level = norm_level(cell(row, 6))
        levels_hist = ", ".join(
            f"{year}: {cell(row, idx)}"
            for year, idx in (("2026", 6), ("2025", 7), ("2024", 8), ("2023", 9), ("2022", 10))
            if cell(row, idx) and cell(row, idx) != "-"
        )
        for idx, benefit in ((4, BVI), (5, STO)):
            if cell(row, idx) != "+":
                continue
            yield DetailRow(
                university="Финансовый университет при Правительстве РФ",
                program_name=f"{group}: программы с ВИ по предмету «{subject}»",
                benefit_type=benefit,
                olympiad_name=olympiad,
                olympiad_profile=profile,
                olympiad_subject=subject,
                level=level,
                confirm_subject=subject,
                min_ege="75",
                winner_role="победители и призёры",
                conditions=join_parts(olympiad, f"профиль: {profile}" if profile else "",
                                      f"уровень {level}" if level else "",
                                      f"предмет группы: {subject}"),
                note=f"Уровни по годам — {levels_hist}" if levels_hist else "",
                source_url=url,
            )


def adapt_kfu(rows: Iterable[Sequence]) -> Iterator[DetailRow]:
    for row in rows:
        olympiad = clean_name(cell(row, 0))
        if not olympiad:
            continue
        profile = cell(row, 1)
        subjects_of_profile = cell(row, 2)
        level = norm_level(cell(row, 3))
        vi_subjects = [s.strip() for s in cell(row, 4).split(",") if s.strip()]
        directions = cell(row, 5)
        conditions = join_parts(olympiad, f"профиль: {profile}" if profile else "",
                                f"уровень {level}" if level else "", "победители и призёры")
        common = dict(
            university="Казанский (Приволжский) федеральный университет (КФУ)",
            benefit_type=BVI,
            olympiad_name=olympiad,
            olympiad_profile=profile,
            olympiad_subject=subjects_of_profile,
            level=level,
            winner_role="победители и призёры",
            min_ege="75",
            conditions=conditions,
            note="Если БВИ не используется — 100 баллов по предмету, соответствующему профилю",
        )
        codes = extract_codes(directions)
        if codes and not directions.lower().startswith("на все направления"):
            for code, name in parse_code_names(directions):
                yield DetailRow(program_name=f"{code} {name}".strip(), code=code,
                                confirm_subject=", ".join(vi_subjects), **common)
        else:
            for subject in vi_subjects or ["профильный предмет"]:
                yield DetailRow(program_name=f"Все направления с ВИ по предмету «{subject}»",
                                confirm_subject=subject, **common)


def parse_code_names(text: str) -> List[Tuple[str, str]]:
    """«07.03.01 Архитектура 44.03.04 Проф. обучение» -> [(код, название), ...]"""
    parts = re.split(r"(\d{2}\.\d{2}\.\d{2})", clean_text(text))
    out: List[Tuple[str, str]] = []
    for i in range(1, len(parts), 2):
        code = parts[i]
        name = clean_text(parts[i + 1] if i + 1 < len(parts) else "")
        out.append((code, name.strip(" ,;.")[:120]))
    return out


def adapt_urfu(rows: Iterable[Sequence], legend: Dict[str, str]) -> Iterator[DetailRow]:
    url = "https://urfu.ru/fileadmin/user_upload/urfu.ru/documents/applicant/2026/Lgoty_olimpiadnikam.pdf"
    vsosh = "Всероссийская олимпиада школьников (заключительный этап)"
    for row in rows:
        direction = cell(row, 0)
        if not direction:
            continue
        codes = extract_codes(direction)
        program = direction
        code = codes[0] if codes else ""
        rsosh_profiles = cell(row, 5) or decode_codes(cell(row, 1), legend)
        sto_subjects = decode_subjects(cell(row, 2))
        vsosh_bvi = cell(row, 6) or decode_subjects(cell(row, 3))
        vsosh_sto = decode_subjects(cell(row, 4))
        base = dict(university="Уральский федеральный университет (УрФУ)",
                    program_name=program, code=code, source_url=url)
        if rsosh_profiles:
            yield DetailRow(
                benefit_type=BVI,
                olympiad_profile=rsosh_profiles,
                level="I, II, III",
                winner_role="победители и призёры",
                min_ege="75",
                conditions=f"Перечневые олимпиады I–III уровня по профилям: {rsosh_profiles}",
                note="Правило УрФУ задано профилем олимпиады, а не её названием: подходит любая "
                     "олимпиада перечня с этим профилем (ЕГЭ ≥75 по предмету профиля)",
                **base,
            )
        if vsosh_bvi:
            yield DetailRow(
                benefit_type=BVI,
                olympiad_name=vsosh,
                olympiad_subject=vsosh_bvi,
                winner_role="победители и призёры",
                conditions=f"ВсОШ (заключительный этап), предметы: {vsosh_bvi}",
                note="ВсОШ — без подтверждения ЕГЭ",
                **base,
            )
        if sto_subjects:
            yield DetailRow(
                benefit_type=STO,
                olympiad_profile=rsosh_profiles,
                award_subject=sto_subjects,
                min_ege="75",
                conditions=f"Перечневые олимпиады — 100 баллов по предметам: {sto_subjects}",
                **base,
            )
        if vsosh_sto:
            yield DetailRow(
                benefit_type=STO,
                olympiad_name=vsosh,
                award_subject=vsosh_sto,
                conditions=f"ВсОШ — 100 баллов по предметам: {vsosh_sto}",
                **base,
            )


def decode_codes(value: str, legend: Dict[str, str]) -> str:
    out = []
    for token in clean_text(value).split(","):
        token = token.strip()
        if not token:
            continue
        out.append(legend.get(token.lower(), token))
    return ", ".join(out)


def decode_subjects(value: str) -> str:
    out = []
    for token in clean_text(value).split(","):
        token = token.strip().lower()
        if not token:
            continue
        out.append(URFU_SUBJECTS.get(token, token))
    return ", ".join(out)


def adapt_cu(rows: Iterable[Sequence]) -> Iterator[DetailRow]:
    for row in rows:
        olympiad = clean_name(cell(row, 1))
        if not olympiad or cell(row, 6).lower() not in ("да", "yes", "+"):
            continue
        profile = cell(row, 2)
        level = norm_level(cell(row, 4))
        subject = cell(row, 5)
        yield DetailRow(
            university="Центральный университет (ЦУ, АНО ВО)",
            program_name="Фаст-трек грантового конкурса (все программы бакалавриата)",
            benefit_type=FASTTRACK,
            olympiad_name=olympiad,
            olympiad_profile=profile,
            olympiad_subject=cell(row, 3),
            level=level,
            confirm_subject=subject,
            years=cell(row, 0),
            winner_role="победители и призёры",
            conditions=join_parts(olympiad, f"профиль: {profile}" if profile else "",
                                  f"уровень {level}" if level else "",
                                  f"ВИ ЦУ: {subject}" if subject else ""),
            note="Фаст-трек грантового конкурса: размер гранта определяется по собеседованию",
            source_url="https://cu.ru/olympiad",
        )


def adapt_innopolis(rows: Iterable[Sequence]) -> Iterator[DetailRow]:
    programs = [("09.03.01", "09.03.01 Информатика и вычислительная техника"),
                ("15.03.06", "15.03.06 Робототехника и мехатроника")]
    for row in rows:
        olympiad = clean_name(cell(row, 1))
        if not olympiad:
            continue
        profile = cell(row, 2)
        level = norm_level(cell(row, 4))
        subject = cell(row, 5)
        for code, name in programs:
            yield DetailRow(
                university="Университет Иннополис (АНО ВО)",
                program_name=name,
                code=code,
                benefit_type=SPECIAL,
                olympiad_name=olympiad,
                olympiad_profile=profile,
                olympiad_subject=cell(row, 3),
                level=level,
                confirm_subject=subject,
                years=cell(row, 0),
                min_ege="75",
                winner_role="победители и призёры",
                conditions=join_parts(olympiad, f"профиль: {profile}" if profile else "",
                                      f"уровень {level}" if level else "",
                                      f"ВИ: {subject}" if subject else ""),
                note="Какое именно право (БВИ или 100 баллов) применяется — определяют правила "
                     "приёма университета; подтверждение ЕГЭ ≥75",
                source_url="https://innopolis.university/sveden/apply/",
            )


def adapt_pirogov(rows: Iterable[Sequence]) -> Iterator[DetailRow]:
    """Пирогова: 812 строк по годам -> агрегируем по (олимпиада, профиль, уровень, предмет)."""
    agg: Dict[Tuple[str, str, str, str, str], Dict[str, Set[str]]] = {}
    for row in rows:
        olympiad = clean_name(cell(row, 2))
        if not olympiad:
            continue
        profile = cell(row, 3)
        level = norm_level(cell(row, 4))
        bvi_subject = cell(row, 5)
        sto_subjects = cell(row, 6)
        key = (olympiad, profile, level, bvi_subject, sto_subjects)
        bucket = agg.setdefault(key, {"years": set(), "id": set()})
        if cell(row, 1):
            bucket["years"].add(cell(row, 1))
        if cell(row, 7):
            bucket["id"].add(cell(row, 7))

    for (olympiad, profile, level, bvi_subject, sto_subjects), bucket in agg.items():
        years = ", ".join(sorted(bucket["years"]))
        id_points = ", ".join(sorted(bucket["id"]))
        note = f"Дипломы за {years}" if years else ""
        if id_points:
            note = join_parts(note, f"как индивидуальное достижение: {id_points} балл(ов)")
        common = dict(
            university="РНИМУ им. Н.И. Пирогова (Пироговский университет)",
            olympiad_name=olympiad,
            olympiad_profile=profile,
            level=level,
            winner_role="победители и призёры (10–11 класс)",
            min_ege="75",
            years=years,
            note=note,
        )
        if bvi_subject:
            yield DetailRow(
                program_name=f"Все направления с ВИ по предмету «{bvi_subject}»",
                benefit_type=BVI,
                confirm_subject=bvi_subject,
                conditions=join_parts(olympiad, f"профиль: {profile}" if profile else "",
                                      f"уровень {level}" if level else "",
                                      f"профилирующий предмет: {bvi_subject}"),
                **common,
            )
        for subject in [s.strip() for s in sto_subjects.split(",") if s.strip()]:
            if subject == bvi_subject:
                continue
            yield DetailRow(
                program_name=f"Все направления с ВИ по предмету «{subject}»",
                benefit_type=STO,
                confirm_subject=subject,
                award_subject=subject,
                conditions=join_parts(olympiad, f"профиль: {profile}" if profile else "",
                                      f"уровень {level}" if level else "",
                                      f"100 баллов по предмету: {subject}"),
                **common,
            )


def adapt_urfu_extra(rows: Iterable[Sequence]) -> Iterator[DetailRow]:
    for row in rows:
        unit = cell(row, 0)
        event = clean_name(cell(row, 1))
        subject = cell(row, 2)
        if not event:
            continue
        yield DetailRow(
            university="Уральский федеральный университет (УрФУ)",
            program_name=f"Направления с ВИ по предмету «{subject}»" if subject else unit,
            benefit_type=EXTRA_POINTS,
            olympiad_name=event,
            olympiad_subject=subject,
            confirm_subject=subject,
            years=cell(row, 3),
            conditions=join_parts(event, unit, f"предмет: {subject}" if subject else "",
                                  cell(row, 4) or "+4 балла к сумме (ИД)"),
            note=f"Мероприятие УрФУ ({unit}); предмет должен входить в ВИ направления",
            source_url="https://urfu.ru/ru/applicant/",
        )


# ==========================================================================
#  основной конвейер
# ==========================================================================


class Ingestor:
    def __init__(self, xlsx_path: str, db_path: str) -> None:
        self.xlsx_path = xlsx_path
        self.db_path = db_path
        self.conn: sqlite3.Connection
        self.catalog = OlympiadCatalog()
        self.matcher = OlympiadMatcher()
        self.programs: ProgramRegistry
        self.universities: Dict[str, int] = {}
        self.uni_squash: Dict[str, int] = {}
        self.olympiad_ids: Dict[str, int] = {}     # squash key -> olympiad id
        self.olympiad_names: Dict[int, str] = {}   # olympiad id -> короткое название
        self.olympiad_kinds: Dict[int, str] = {}   # olympiad id -> rsosh | vsosh | international
        self.profile_ids: Dict[Tuple[int, str], int] = {}   # (olympiad_id, ключ) -> profile id
        self.seen_rows: Dict[Tuple, int] = {}               # ключ строки таблицы -> benefit id
        self.stats: Counter = Counter()
        self.sheet_log: List[Tuple[str, int, int, int, str]] = []

    # -- инфраструктура ---------------------------------------------------
    def connect(self) -> None:
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as fh:
            self.conn.executescript(fh.read())
        self.programs = ProgramRegistry(self.conn)

    def run(self) -> None:
        started = time.time()
        log(f"[1/7] Читаю {self.xlsx_path}")
        wb = openpyxl.load_workbook(self.xlsx_path, read_only=True, data_only=True)
        log(f"      листов: {len(wb.sheetnames)} -> {', '.join(wb.sheetnames)}")

        self.connect()

        log("[2/7] Собираю справочник олимпиад")
        self.catalog.build(wb)
        international = self.catalog.add_international(wb)
        self.save_catalog()
        log(f"      канонических олимпиад: {len(self.catalog.items)}")

        log("[3/7] Лист «База»")
        self.ingest_base(wb)

        log("[4/7] Подробные листы")
        self.ingest_details(wb)
        self.ingest_international(international)
        self.fill_source_fallbacks()

        log("[5/7] Разбор текстовых правил и ключевые слова")
        self.expand_summaries()
        self.update_counters()
        merged = self.merge_profile_fragments()
        if merged:
            log(f"      склеено обрывков профилей: {merged}")
            self.update_counters()
        self.profile_levels()
        self.expand_profile_rules()
        self.apply_university_pages()
        self.apply_official_sources()
        merged = self.merge_profile_fragments()
        if merged:
            log(f"      склеено обрывков профилей: {merged}")
        self.extract_keywords()

        log("[6/7] Полнотекстовый индекс")
        self.build_fts()

        log("[7/7] Статистика")
        self.finalize(started)
        wb.close()
        self.conn.commit()
        self.conn.close()

    # -- справочник -------------------------------------------------------
    def save_catalog(self) -> None:
        for item in self.catalog.items:
            cur = self.conn.execute(
                """INSERT INTO olympiads (canonical_name, short_name, squash_key, kind,
                                          is_featured, mentions)
                   VALUES (?,?,?,?,?,?)""",
                (item.canonical_name, item.short_name or item.canonical_name[:40],
                 sorted(item.squash_keys)[0] if item.squash_keys else squash(item.canonical_name),
                 item.kind, int(item.featured), item.mentions),
            )
            item.db_id = int(cur.lastrowid)
            self.olympiad_names[item.db_id] = item.short_name or item.canonical_name
            self.olympiad_kinds[item.db_id] = item.kind
            aliases = set(item.aliases) | {item.canonical_name, item.short_name}
            for alias in aliases:
                alias = clean_text(alias)
                if not alias:
                    continue
                sq = squash(alias)
                if len(sq) < 2:
                    continue
                self.conn.execute(
                    """INSERT OR IGNORE INTO olympiad_aliases
                       (olympiad_id, alias, squash_alias, is_generic) VALUES (?,?,?,?)""",
                    (item.db_id, alias, sq, int(len(sq) < 16)),
                )
                self.matcher.add(item.db_id, alias, is_generic=len(sq) < 16)
            for key in item.squash_keys:
                self.olympiad_ids[key] = item.db_id

    def olympiad_id_for(self, name: str) -> Optional[int]:
        if not name:
            return None
        key = squash(name)
        if key in self.olympiad_ids:
            return self.olympiad_ids[key]
        found = self.matcher.exact(name)
        if found:
            self.olympiad_ids[key] = found
            return found
        hits = self.matcher.find(name)
        if hits:
            self.olympiad_ids[key] = hits[0].olympiad_id
            return hits[0].olympiad_id
        return None

    # -- университеты -----------------------------------------------------
    @staticmethod
    def region_group(region: str) -> str:
        r = clean_text(region)
        if "Москва" in r and "область" not in r.lower():
            return "Москва"
        if "Петербург" in r:
            return "Санкт-Петербург"
        return "Регионы"

    @staticmethod
    def short_university(name: str) -> str:
        s = re.sub(r"\s*\(АНО ВО\)\s*$", "", clean_text(name))
        m = re.search(r"\(([^)]{2,24})\)\s*$", s)
        if m:
            token = m.group(1).split(",")[0].strip()
            if token.isupper() and 2 <= len(token) <= 12 and token not in ("АНО", "ВО", "АНО ВО"):
                return token
        return s if len(s) <= 34 else s[:33] + "…"

    @staticmethod
    def city_for(name: str, region: str) -> str:
        """Город для таблиц: «Приволжский ФО» -> «Казань»."""
        key = squash(name)
        for hint, city in CITY_HINTS.items():
            if hint in key:
                return city
        region = clean_text(region)
        if not region or region.endswith("ФО") or "филиал" in region.lower():
            return ""
        return region

    def university_id(self, name: str, region: str = "") -> int:
        name = clean_text(name)
        if not name:
            name = "Не указан"
        if name in self.universities:
            uid = self.universities[name]
            if region:
                self.conn.execute(
                    "UPDATE universities SET region=?, region_group=?, city=? WHERE id=? AND region=''",
                    (region, self.region_group(region), self.city_for(name, region), uid),
                )
            return uid
        key = squash(name)
        if key in self.uni_squash:
            return self.uni_squash[key]
        note = next((text for hint, text in UNIVERSITY_NOTES.items() if hint in key), "")
        cur = self.conn.execute(
            "INSERT INTO universities (name, short_name, region, city, note, region_group)"
            " VALUES (?,?,?,?,?,?)",
            (name, self.short_university(name), clean_text(region),
             self.city_for(name, region), note, self.region_group(region)),
        )
        uid = int(cur.lastrowid)
        self.universities[name] = uid
        self.uni_squash[key] = uid
        return uid

    # -- лист «База» ------------------------------------------------------
    def ingest_base(self, wb) -> None:
        ws = wb[SHEET_BASE]
        rows_read = benefits = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            region, university = cell(row, 0), cell(row, 1)
            if not university:
                continue
            rows_read += 1
            uid = self.university_id(university, region)
            faculty, profile = cell(row, 2), cell(row, 3)
            if faculty in ("—", "-", "–"):
                faculty = ""
            if profile in ("—", "-", "–"):
                profile = ""
            note, source = cell(row, 6), cell(row, 7)
            pid = self.programs.get_or_create(
                uid, faculty or profile or "Общие правила", profile=profile,
                note=note, source_url=source, source_sheet=SHEET_BASE,
            )
            for idx, benefit_type in ((4, BVI), (5, STO)):
                text = cell(row, idx)
                if not text or text in ("—", "-", "–"):
                    continue
                self.insert_benefit(
                    DetailRow(university=university, program_name=faculty,
                              benefit_type=benefit_type, conditions=text,
                              note=note, source_url=source),
                    program_id=pid, layer="summary", source_sheet=SHEET_BASE,
                )
                benefits += 1
        self.sheet_log.append((SHEET_BASE, ws.max_row - 1, rows_read, benefits, "сводные правила"))
        log(f"      «База»: {rows_read} строк -> {benefits} льгот")

    # -- подробные листы --------------------------------------------------
    def ingest_details(self, wb) -> None:
        legend = self.read_urfu_legend(wb)
        adapters = [
            ("ВШЭ подробно", adapt_hse, "программа × олимпиада × профиль"),
            ("ВШЭ филиалы подробно", adapt_hse_branches, "кампусы СПб / НН / Пермь"),
            ("ВШЭ ВсОШ", adapt_hse_vsosh, "ВсОШ по программам"),
            ("РЭУ подробно", adapt_rea, "агрегация по годам и предметам ЕГЭ"),
            ("МИФИ подробно", adapt_mephi, "коды направлений раскрыты построчно"),
            ("Бауманка подробно", adapt_bauman, "10 групп направлений"),
            ("Финуниверситет подробно", adapt_finuniver, "группы программ 1–8"),
            ("КФУ подробно", adapt_kfu, "по предмету ВИ и по кодам"),
            ("УрФУ подробно", lambda rows: adapt_urfu(rows, legend), "профили РСОШ раскрыты"),
            ("ЦУ фаст-трек", adapt_cu, "фаст-трек грантового конкурса"),
            ("Иннополис подробно", adapt_innopolis, "особые права по перечню"),
            ("Пирогова подробно", adapt_pirogov, "агрегация по годам"),
            ("УрФУ +4 балла", adapt_urfu_extra, "индивидуальные достижения"),
        ]
        for sheet, adapter, comment in adapters:
            if sheet not in wb.sheetnames:
                log(f"      ! лист «{sheet}» отсутствует — пропускаю")
                continue
            ws = wb[sheet]
            rows = list(ws.iter_rows(min_row=2, values_only=True))
            produced = 0
            for detail in adapter(rows):
                uid = self.university_id(detail.university)
                pid = self.programs.get_or_create(
                    uid, detail.program_name, code=detail.code, profile=detail.profile_name,
                    source_url=detail.source_url, source_sheet=sheet,
                )
                self.insert_benefit(detail, program_id=pid, layer="detailed", source_sheet=sheet)
                produced += 1
            self.sheet_log.append((sheet, len(rows), len(rows), produced, comment))
            log(f"      «{sheet}»: {len(rows)} строк -> {produced} льгот")

        for sheet in ("УрФУ легенда", "Сводка по вузам", "ВШЭ международные"):
            if sheet in wb.sheetnames:
                ws = wb[sheet]
                self.sheet_log.append((sheet, ws.max_row - 1, 0, 0, "справочный лист"))

    def fill_source_fallbacks(self) -> None:
        """
        У части строк «Базы» колонка «Источник» пуста. Берём самый частый документ
        этого же вуза, чтобы из карточки направления всегда можно было перейти
        к первоисточнику и перепроверить распарсенную таблицу.
        """
        best: Dict[int, Tuple[str, str]] = {}
        rows = self.conn.execute(
            """SELECT university_id, source_title, source_url, COUNT(*) AS cnt
               FROM programs WHERE source_url <> ''
               GROUP BY university_id, source_url ORDER BY university_id, cnt DESC"""
        ).fetchall()
        for university_id, title, url, _ in rows:
            best.setdefault(university_id, (title, url))

        self.conn.executemany(
            "UPDATE universities SET site_url=? WHERE id=?",
            [(url, uid) for uid, (_, url) in best.items()],
        )
        filled = 0
        for university_id, (title, url) in best.items():
            cur = self.conn.execute(
                """UPDATE programs SET source_title = CASE WHEN source_title = '' THEN ?
                                                           ELSE source_title END,
                                       source_url = ?
                   WHERE university_id = ? AND source_url = ''""",
                (title, url, university_id),
            )
            filled += cur.rowcount
        # вузы, у которых в таблице нет ни одной ссылки — ведём на приёмную комиссию
        from_catalog = 0
        for uid, name in self.conn.execute(
            """SELECT u.id, u.name FROM universities u
               WHERE EXISTS (SELECT 1 FROM programs p
                             WHERE p.university_id = u.id AND p.source_url = '')"""
        ).fetchall():
            key = squash(name)
            hit = next(((t, url) for part, (t, url) in UNIVERSITY_SOURCES.items() if part in key), None)
            if not hit:
                continue
            title, url = hit
            cur = self.conn.execute(
                """UPDATE programs SET source_title = CASE WHEN source_title = '' THEN ?
                                                           ELSE source_title END,
                                       source_url = ?
                   WHERE university_id = ? AND source_url = ''""",
                (title, url, uid),
            )
            from_catalog += cur.rowcount
            self.conn.execute("UPDATE universities SET site_url=? WHERE id=? AND site_url=''",
                              (url, uid))

        missing = self.conn.execute(
            "SELECT COUNT(*) FROM programs WHERE source_url = ''").fetchone()[0]
        log(f"      источники: подставлено по вузу {filled}, по справочнику приёмных комиссий "
            f"{from_catalog}, осталось без ссылки {missing}")

    def apply_university_pages(self) -> None:
        """
        Проставляет вузам стабильную страницу раздела с документами и подтягивает
        файлы, найденные на ней скриптом refresh_sources.py (кэш в data/).
        """
        cache: Dict[str, Dict] = {}
        if os.path.exists(SOURCES_CACHE):
            try:
                with open(SOURCES_CACHE, encoding="utf-8") as fh:
                    cache = json.load(fh)
            except Exception as exc:
                log(f"      ! кэш документов не прочитан: {exc}")

        pages = documents = 0
        stamp = time.strftime("%Y-%m-%d")
        for uid, name in self.conn.execute("SELECT id, name FROM universities").fetchall():
            key = squash(name)
            page = next((p for part, p in PAGES.items() if part in key), None)
            if page:
                self.conn.execute(
                    "UPDATE universities SET docs_url=?, docs_title=? WHERE id=?",
                    (page.url, page.title, uid))
                pages += 1
            entry = cache.get(name)
            if not entry:
                continue
            for doc in entry.get("documents", []):
                self.conn.execute(
                    """INSERT OR REPLACE INTO university_documents
                       (university_id, title, url, checked_at) VALUES (?,?,?,?)""",
                    (uid, doc.get("title", "Документ"), doc["url"],
                     entry.get("checked_at", stamp)))
                documents += 1
        log(f"      страниц вузов проставлено: {pages}, файлов из кэша: {documents}")

    def apply_official_sources(self) -> None:
        """
        Ссылка «на страницу приёмной комиссии» бесполезна: человек должен попадать
        сразу в документ, по которому собрана таблица. Справочник OFFICIAL_SOURCES
        перекрывает такие ссылки проверенными PDF, в том числе отдельными для БВИ
        и для 100 баллов (так устроены приложения ИТМО).
        """
        overridden = 0
        for uid, name in self.conn.execute("SELECT id, name FROM universities").fetchall():
            key = squash(name)
            docs = next((d for part, d in OFFICIAL_SOURCES.items() if part in key), None)
            if not docs:
                continue
            for benefit_type, (title, url) in docs.items():
                if benefit_type == "*":
                    continue
                cur = self.conn.execute(
                    """UPDATE benefits SET source_title=?, source_url=?
                       WHERE benefit_type=? AND program_id IN
                             (SELECT id FROM programs WHERE university_id=?)""",
                    (title, url, benefit_type, uid))
                overridden += cur.rowcount
            title, url = docs.get("*", ("", ""))
            if url:
                self.conn.execute(
                    "UPDATE programs SET source_title=?, source_url=? WHERE university_id=?",
                    (title, url, uid))
                self.conn.execute("UPDATE universities SET site_url=? WHERE id=?", (url, uid))
        log(f"      прямых документов подставлено: {overridden}")

    def read_urfu_legend(self, wb) -> Dict[str, str]:
        legend: Dict[str, str] = {}
        if "УрФУ легенда" not in wb.sheetnames:
            return legend
        for row in wb["УрФУ легенда"].iter_rows(min_row=2, values_only=True):
            code, profile = cell(row, 0), cell(row, 1)
            if code and profile:
                legend[code.lower()] = profile
        return legend

    def ingest_international(self, pairs: List[Tuple[CanonicalOlympiad, str]]) -> None:
        if not pairs:
            return
        uid = self.university_id("НИУ ВШЭ (Москва)", "Москва")
        pid = self.programs.get_or_create(
            uid, "Международные олимпиады: БВИ членам сборных РФ",
            note="Приложение 3 НИУ ВШЭ: члены сборных команд РФ на международных олимпиадах "
                 "получают БВИ на направления, соответствующие предмету олимпиады",
            source_url=HSE_SOURCE, source_sheet="ВШЭ международные",
        )
        count = 0
        for item, subject in pairs:
            benefit_id = self.insert_benefit(
                DetailRow(university="НИУ ВШЭ (Москва)",
                          program_name="Международные олимпиады: БВИ членам сборных РФ",
                          benefit_type=BVI,
                          olympiad_name=item.canonical_name,
                          olympiad_subject=subject,
                          winner_role="члены сборных команд РФ",
                          conditions=f"{item.canonical_name} ({item.short_name}) — предмет соответствия: {subject}",
                          note="БВИ по ч. 4 ст. 71 273-ФЗ — члены сборных команд РФ"),
                program_id=pid, layer="detailed", source_sheet="ВШЭ международные",
            )
            count += 1
        self.stats["international"] = count
        log(f"      «ВШЭ международные»: {count} олимпиад -> БВИ членам сборных")

    # -- вставка льготы ---------------------------------------------------
    def insert_benefit(self, detail: DetailRow, program_id: int, layer: str,
                       source_sheet: str) -> int:
        # В исходных листах одна и та же строка иногда повторяется (артефакт вёрстки
        # PDF). Для таблиц это мусор, поэтому полностью идентичные строки пропускаем.
        # каноническая олимпиада: в источниках одна и та же олимпиада за разные годы
        # называется по-разному, поэтому в ключе строки должен быть id справочника
        olympiad_id = detail.olympiad_id or (
            self.olympiad_id_for(detail.olympiad_name) if detail.olympiad_name else 0)

        if layer in ("detailed", "derived"):
            key = (
                program_id, detail.benefit_type,
                olympiad_id or squash(detail.olympiad_name), squash(detail.olympiad_profile),
                squash(detail.olympiad_subject), detail.level, detail.winner_role,
                detail.grade, squash(detail.confirm_subject), detail.min_ege,
            )
            twin = self.seen_rows.get(key)
            if twin is not None:
                # строки-близнецы обычно отличаются только годом диплома — сливаем годы
                self.merge_years(twin, detail.years)
                self.stats["duplicates"] += 1
                return twin
            self.seen_rows[key] = 0   # id проставим после вставки

        source_title, source_link = split_source(detail.source_url)
        cur = self.conn.execute(
            """INSERT INTO benefits
               (program_id, benefit_type, raw_conditions_text, layer, olympiad_profile,
                olympiad_subject, level, winner_role, grade, confirm_subject, min_ege,
                award_subject, years, note, source_title, source_url, source_sheet)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (program_id, detail.benefit_type, detail.conditions or detail.olympiad_name, layer,
             detail.olympiad_profile, detail.olympiad_subject, detail.level, detail.winner_role,
             detail.grade, detail.confirm_subject, detail.min_ege, detail.award_subject,
             detail.years, detail.note, source_title, source_link, source_sheet),
        )
        benefit_id = int(cur.lastrowid)
        if layer in ("detailed", "derived"):
            self.seen_rows[key] = benefit_id
        self.stats["benefits"] += 1

        linked = False
        if olympiad_id:
            self.link(benefit_id, olympiad_id, detail.olympiad_profile, detail.level,
                      detail.winner_role, "column")
            linked = True
        if not linked:
            for hit in self.matcher.find(detail.conditions):
                self.link(benefit_id, hit.olympiad_id, detail.olympiad_profile, detail.level,
                          detail.winner_role, "text")
        return benefit_id

    def profile_id_for(self, olympiad_id: int, profile: str) -> Optional[int]:
        """Профиль — отдельная сущность: льгота даётся за пару «олимпиада + профиль»."""
        name = clean_profile(profile)[:300]
        if not name:
            return None
        key = squash(name)
        if len(key) < 2:
            return None
        cached = self.profile_ids.get((olympiad_id, key))
        if cached is not None:
            return cached
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO olympiad_profiles (olympiad_id, name, squash_key) VALUES (?,?,?)",
            (olympiad_id, name, key),
        )
        profile_id = int(cur.lastrowid) if cur.rowcount else int(
            self.conn.execute(
                "SELECT id FROM olympiad_profiles WHERE olympiad_id=? AND squash_key=?",
                (olympiad_id, key),
            ).fetchone()[0]
        )
        self.profile_ids[(olympiad_id, key)] = profile_id
        return profile_id

    def merge_years(self, benefit_id: int, years: str) -> None:
        """«2026» + «2023, 2024» -> «2023, 2024, 2026» в уже вставленной строке."""
        new = {y.strip() for y in clean_text(years).split(",") if y.strip()}
        if not new or not benefit_id:
            return
        row = self.conn.execute("SELECT years FROM benefits WHERE id=?", (benefit_id,)).fetchone()
        current = {y.strip() for y in (row[0] or "").split(",") if y.strip()}
        if new <= current:
            return
        self.conn.execute("UPDATE benefits SET years=? WHERE id=?",
                          (", ".join(sorted(current | new)), benefit_id))

    def link(self, benefit_id: int, olympiad_id: int, profile: str, level: str,
             role: str, via: str) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO benefit_olympiads
               (benefit_id, olympiad_id, profile_id, profile, level, winner_role, matched_via)
               VALUES (?,?,?,?,?,?,?)""",
            (benefit_id, olympiad_id, self.profile_id_for(olympiad_id, profile),
             clean_profile(profile)[:300], clean_text(level), clean_text(role), via),
        )
        self.stats["links"] += 1

    # -- разбор перечислений из «Базы» ------------------------------------
    def expand_summaries(self) -> None:
        """
        Сводные строки «Базы» вида «[143 вар.] «Высшая проба» (информатика, I ур.); …»
        раскладываем в те же табличные строки, что и подробные листы.

        Если подробный лист уже покрывает это направление — текст просто помечаем
        как `raw` (он дублирует таблицу). Если в тексте вообще нет названий олимпиад
        (общие правила вуза) — он остаётся `summary` и показывается примечанием.
        """
        rows = self.conn.execute(
            """SELECT b.id, b.program_id, b.benefit_type, b.raw_conditions_text, b.note,
                      b.source_url, b.min_ege,
                      (SELECT COUNT(*) FROM benefits d WHERE d.program_id = b.program_id
                         AND d.layer = 'detailed' AND d.benefit_type = b.benefit_type)
               FROM benefits b WHERE b.layer = 'summary'"""
        ).fetchall()

        added = hidden = kept = 0
        for bid, program_id, btype, text, note, url, min_ege, detailed in rows:
            resolved = self.resolve_enumeration(text)
            if not resolved:
                kept += 1
                continue
            self.conn.execute("UPDATE benefits SET layer='raw' WHERE id=?", (bid,))
            hidden += 1
            if detailed:
                continue      # подробный лист уже дал эти строки
            seen: Set[Tuple] = set()
            for olympiad_id, profile, subject, item in resolved:
                key = (olympiad_id, squash(profile), item.level, item.role, item.grade)
                if key in seen:
                    continue
                seen.add(key)
                name = self.olympiad_names.get(olympiad_id, item.name)
                detail = DetailRow(
                    university="", program_name="", benefit_type=btype,
                    olympiad_name=name, olympiad_id=olympiad_id,
                    olympiad_profile=profile, olympiad_subject=subject,
                    level=item.level, winner_role=item.role, grade=item.grade,
                    confirm_subject=subject, min_ege=min_ege, note=note, source_url=url,
                    conditions=join_parts(name, f"профиль: {profile}" if profile else "",
                                          f"уровень {item.level}" if item.level else "",
                                          item.role, item.grade),
                )
                self.insert_benefit(detail, program_id=program_id, layer="detailed",
                                    source_sheet="База (разбор текста)")
                added += 1
        self.stats["expanded"] = added
        log(f"      разобрано перечислений: +{added} строк, скрыто дублей текста: {hidden}, "
            f"осталось текстовых правил: {kept}")

    # -- правила «любая олимпиада перечня по профилю X» ---------------------
    def expand_profile_rules(self) -> None:
        """
        Часть вузов (ИТМО, УрФУ, Горный) задаёт льготу профилем олимпиады, а не её
        названием: «любая олимпиада перечня I–III уровня по информатике», «все
        технологические профили (… мобильные приложения …) — БВИ». Раскрываем такие
        правила в конкретные пары «олимпиада + профиль» по справочнику профилей.
        """
        index = ProfileIndex()
        meta: Dict[int, Tuple[int, str, str]] = {}
        for pid, olympiad_id, name, level in self.conn.execute(
            "SELECT id, olympiad_id, name, level FROM olympiad_profiles WHERE mentions >= 2"
        ):
            index.add(pid, name)
            meta[pid] = (olympiad_id, name, level)

        sources = self.conn.execute(
            """SELECT b.id, b.program_id, b.benefit_type, b.raw_conditions_text, b.note,
                      b.source_url, b.min_ege, b.confirm_subject
               FROM benefits b
               WHERE b.layer IN ('summary', 'raw')
                  OR (b.layer = 'detailed'
                      AND NOT EXISTS (SELECT 1 FROM benefit_olympiads bo WHERE bo.benefit_id = b.id))"""
        ).fetchall()

        seen_by_program: Dict[Tuple[int, str], Set[Tuple[int, int]]] = {}
        added = rules_used = 0
        for bid, program_id, btype, text, note, url, min_ege, confirm in sources:
            rules = parse_profile_rules(text)
            if not rules:
                continue
            key = (program_id, btype)
            if key not in seen_by_program:
                seen_by_program[key] = {
                    (row[0], row[1]) for row in self.conn.execute(
                        """SELECT bo.olympiad_id, bo.profile_id FROM benefit_olympiads bo
                           JOIN benefits b ON b.id = bo.benefit_id
                           WHERE b.program_id = ? AND b.benefit_type = ? AND bo.profile_id IS NOT NULL""",
                        (program_id, btype))
                }
            seen = seen_by_program[key]
            produced = 0
            for rule in rules:
                # ВсОШ и так прописана отдельными строками в каждом листе —
                # раскрытие её «по профилю» дало бы только дубли
                if rule.scope == "vsosh":
                    continue
                for token in rule.profiles:
                    for profile_id in index.find(token):
                        olympiad_id, profile_name, profile_level = meta[profile_id]
                        kind = self.olympiad_kinds.get(olympiad_id, "rsosh")
                        # «перечневые олимпиады» — это РСОШ, ВсОШ идёт отдельным правилом
                        if rule.scope == "rsosh" and kind == "vsosh":
                            continue
                        if rule.scope == "vsosh" and kind != "vsosh":
                            continue
                        if rule.levels and profile_level and profile_level not in rule.levels:
                            continue
                        if (olympiad_id, profile_id) in seen:
                            continue
                        seen.add((olympiad_id, profile_id))
                        name = self.olympiad_names.get(olympiad_id, "")
                        level = profile_level or ", ".join(rule.levels)
                        self.insert_benefit(
                            DetailRow(
                                university="", program_name="", benefit_type=btype,
                                olympiad_name=name, olympiad_id=olympiad_id,
                                olympiad_profile=profile_name, level=level,
                                winner_role=rule.role or "победители и призёры",
                                confirm_subject=confirm, min_ege=min_ege,
                                note="Правило вуза: любая олимпиада перечня с этим профилем",
                                source_url=url,
                                conditions=join_parts(name, f"профиль: {profile_name}",
                                                      f"уровень {level}" if level else ""),
                            ),
                            program_id=program_id, layer="derived",
                            source_sheet="Правило по профилю",
                        )
                        added += 1
                        produced += 1
                        if produced >= 300:   # защита от патологических правил
                            break
                    if produced >= 300:
                        break
                if produced >= 300:
                    break
            if produced:
                rules_used += 1
        self.stats["derived"] = added
        log(f"      правил «по профилю» раскрыто: {rules_used} -> +{added} строк")

    def resolve_enumeration(self, text: str):
        """Строки перечисления -> [(olympiad_id, профиль, предмет, ParsedCondition)]."""
        out = []
        for item in parse_enumeration(text):
            hits = self.matcher.find(item.name)
            if hits:
                for hit in hits:
                    out.append((hit.olympiad_id, item.profile, "", item))
                continue
            # формат «предмет: олимпиада, олимпиада» (ИТМО, НГУ) — слева должен стоять
            # именно учебный предмет, иначе это просто проза и брать её в таблицу нельзя
            subjects = find_subjects(item.name) if len(item.name) <= 60 else []
            subject = subjects[0] if subjects else ""
            for hit in self.matcher.find(item.profile):
                out.append((hit.olympiad_id, "", subject, item))
        return out

    # -- ключевые слова ---------------------------------------------------
    def extract_keywords(self) -> None:
        # у выведенных строк все атрибуты и так структурированы — слова из них не нужны
        rows = self.conn.execute(
            """SELECT id, raw_conditions_text, level, winner_role, grade, min_ege,
                      confirm_subject, olympiad_profile, olympiad_subject
               FROM benefits WHERE layer <> 'derived'"""
        ).fetchall()
        payload: List[Tuple[int, str, str]] = []
        for (bid, text, level, role, grade, min_ege, confirm, profile, subject) in rows:
            found: Set[Tuple[str, str]] = set()
            for lvl in ([level] if level else []) + find_levels(text):
                for token in re.split(r"[,\s]+", lvl):
                    token = token.strip()
                    if token in ("I", "II", "III"):
                        found.add(("level", token))
            for r in ([role] if role else []) + find_roles(text):
                if r:
                    found.add(("role", r))
            for g in find_grades(text) + find_grades(grade):
                found.add(("grade", g))
            for e in ([min_ege] if min_ege.isdigit() else []) + find_ege_thresholds(text):
                found.add(("ege", e))
            for s in find_subjects(" ".join([text, confirm, profile, subject])):
                found.add(("subject", s))
            for kind, keyword in found:
                payload.append((bid, kind, keyword))
        self.conn.executemany(
            "INSERT OR IGNORE INTO benefit_keywords (benefit_id, kind, keyword) VALUES (?,?,?)",
            payload,
        )
        self.stats["keywords"] = len(payload)
        log(f"      ключевых слов: {len(payload)}")

        self.update_counters()

    def profile_levels(self) -> None:
        """Преобладающий уровень пары «олимпиада + профиль» — из подробных листов."""
        rows = self.conn.execute(
            """SELECT profile_id, level, COUNT(*) AS cnt FROM benefit_olympiads
               WHERE profile_id IS NOT NULL AND level IN ('I','II','III')
               GROUP BY profile_id, level ORDER BY profile_id, cnt DESC"""
        ).fetchall()
        best: Dict[int, Tuple[str, int]] = {}
        for profile_id, level, cnt in rows:
            if profile_id not in best or cnt > best[profile_id][1]:
                best[profile_id] = (level, cnt)
        self.conn.executemany(
            "UPDATE olympiad_profiles SET level=? WHERE id=?",
            [(level, pid) for pid, (level, _) in best.items()],
        )
        log(f"      уровень определён для профилей: {len(best)}")

    def update_counters(self) -> None:
        # счётчики по олимпиадам
        self.conn.execute(
            """UPDATE olympiads SET
                 mentions = (SELECT COUNT(*) FROM benefit_olympiads bo WHERE bo.olympiad_id = olympiads.id),
                 bvi_count = (SELECT COUNT(*) FROM benefit_olympiads bo
                              JOIN benefits b ON b.id = bo.benefit_id
                              WHERE bo.olympiad_id = olympiads.id AND b.benefit_type = 'БВИ'),
                 sto_count = (SELECT COUNT(*) FROM benefit_olympiads bo
                              JOIN benefits b ON b.id = bo.benefit_id
                              WHERE bo.olympiad_id = olympiads.id AND b.benefit_type = '100 баллов'),
                 uni_count = (SELECT COUNT(DISTINCT p.university_id) FROM benefit_olympiads bo
                              JOIN benefits b ON b.id = bo.benefit_id
                              JOIN programs p ON p.id = b.program_id
                              WHERE bo.olympiad_id = olympiads.id)"""
        )
        self.conn.execute(
            """UPDATE olympiad_profiles SET
                 mentions = (SELECT COUNT(*) FROM benefit_olympiads bo
                             WHERE bo.profile_id = olympiad_profiles.id),
                 bvi_count = (SELECT COUNT(*) FROM benefit_olympiads bo
                              JOIN benefits b ON b.id = bo.benefit_id
                              WHERE bo.profile_id = olympiad_profiles.id AND b.benefit_type = 'БВИ'),
                 sto_count = (SELECT COUNT(*) FROM benefit_olympiads bo
                              JOIN benefits b ON b.id = bo.benefit_id
                              WHERE bo.profile_id = olympiad_profiles.id AND b.benefit_type = '100 баллов'),
                 uni_count = (SELECT COUNT(DISTINCT p.university_id) FROM benefit_olympiads bo
                              JOIN benefits b ON b.id = bo.benefit_id
                              JOIN programs p ON p.id = b.program_id
                              WHERE bo.profile_id = olympiad_profiles.id)"""
        )
        self.conn.execute("DELETE FROM olympiad_profiles WHERE mentions = 0")
        self.conn.execute("DELETE FROM olympiads WHERE mentions = 0")

    def merge_profile_fragments(self) -> int:
        """
        В PDF профиль иногда разрывается на части: «снимков и геопространствен ных данных»,
        «миры: разработка компьютерных игр…». Такие редкие обрывки приклеиваем к полному
        профилю той же олимпиады — по вхождению подстроки или длинному общему началу.
        """
        merged = 0
        olympiad_ids = [r[0] for r in self.conn.execute(
            "SELECT olympiad_id FROM olympiad_profiles GROUP BY olympiad_id HAVING COUNT(*) > 1")]
        for olympiad_id in olympiad_ids:
            rows = self.conn.execute(
                "SELECT id, squash_key, mentions FROM olympiad_profiles WHERE olympiad_id=?"
                " ORDER BY mentions DESC", (olympiad_id,)).fetchall()
            alive = {pid: (key, mentions) for pid, key, mentions in rows}
            for pid, key, mentions in sorted(rows, key=lambda r: r[2]):
                if mentions > 3 or len(key) < 12 or pid not in alive:
                    continue
                parent = None
                for other_id, (other_key, other_mentions) in alive.items():
                    if other_id == pid or other_mentions <= mentions:
                        continue
                    common = os.path.commonprefix([key, other_key])
                    if key in other_key or other_key in key or len(common) >= 25:
                        if parent is None or other_mentions > alive[parent][1]:
                            parent = other_id
                if parent is None:
                    continue
                self.conn.execute(
                    """UPDATE benefit_olympiads
                       SET profile_id = ?,
                           profile = (SELECT name FROM olympiad_profiles WHERE id = ?)
                       WHERE profile_id = ?""", (parent, parent, pid))
                self.conn.execute("DELETE FROM olympiad_profiles WHERE id=?", (pid,))
                alive.pop(pid, None)
                merged += 1
        return merged

    # -- FTS --------------------------------------------------------------
    def build_fts(self) -> None:
        try:
            # contentless-индекс: сами тексты в нём не дублируются, rowid = benefits.id
            self.conn.execute(
                """CREATE VIRTUAL TABLE search_index USING fts5(
                       olympiads, conditions, program, university, region,
                       content='', tokenize="unicode61 remove_diacritics 2")"""
            )
        except sqlite3.OperationalError as exc:
            log(f"      ! FTS5 недоступен ({exc}); поиск будет работать через LIKE")
            self.conn.execute("INSERT INTO meta (key, value) VALUES ('fts', 'off')")
            return

        rows = self.conn.execute(
            """SELECT b.id, b.raw_conditions_text || ' ' || b.note || ' ' || b.olympiad_profile
                      || ' ' || b.olympiad_subject,
                      p.faculty_or_direction || ' ' || p.profile_name || ' ' || p.code,
                      u.name, u.region,
                      COALESCE((SELECT GROUP_CONCAT(o.canonical_name || ' ' || o.short_name, ' ')
                                FROM benefit_olympiads bo JOIN olympiads o ON o.id = bo.olympiad_id
                                WHERE bo.benefit_id = b.id), '')
               FROM benefits b
               JOIN programs p ON p.id = b.program_id
               JOIN universities u ON u.id = p.university_id
               WHERE b.layer <> 'derived'"""
        ).fetchall()
        self.conn.executemany(
            "INSERT INTO search_index (rowid, conditions, program, university, region, olympiads)"
            " VALUES (?,?,?,?,?,?)",
            [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows],
        )
        self.conn.execute("INSERT INTO meta (key, value) VALUES ('fts', 'on')")
        log(f"      проиндексировано записей: {len(rows)}")

    # -- финал ------------------------------------------------------------
    def finalize(self, started: float) -> None:
        self.conn.executemany(
            "INSERT INTO ingest_log (sheet, rows_read, rows_ingested, benefits, comment)"
            " VALUES (?,?,?,?,?)",
            self.sheet_log,
        )
        counts = {
            "universities": "SELECT COUNT(*) FROM universities",
            "programs": "SELECT COUNT(*) FROM programs",
            # raw — исходные тексты, уже разложенные в строки; в витрине их нет
            "benefits": "SELECT COUNT(*) FROM benefits WHERE layer <> 'raw'",
            "benefits_bvi": "SELECT COUNT(*) FROM benefits WHERE benefit_type='БВИ' AND layer <> 'raw'",
            "benefits_sto": "SELECT COUNT(*) FROM benefits WHERE benefit_type='100 баллов' AND layer <> 'raw'",
            "benefits_raw": "SELECT COUNT(*) FROM benefits WHERE layer = 'raw'",
            "benefits_rows": "SELECT COUNT(*) FROM benefits WHERE layer IN ('detailed','derived')",
            "benefits_derived": "SELECT COUNT(*) FROM benefits WHERE layer = 'derived'",
            "benefits_notes": "SELECT COUNT(*) FROM benefits WHERE layer = 'summary'",
            "olympiads": "SELECT COUNT(*) FROM olympiads",
            "profiles": "SELECT COUNT(*) FROM olympiad_profiles",
            "links": "SELECT COUNT(*) FROM benefit_olympiads",
            "keywords": "SELECT COUNT(*) FROM benefit_keywords",
        }
        for key, sql in counts.items():
            value = self.conn.execute(sql).fetchone()[0]
            self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)",
                              (key, str(value)))
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('source_file', ?)",
            (os.path.basename(self.xlsx_path),),
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('built_at', ?)",
            (time.strftime("%Y-%m-%d %H:%M:%S"),),
        )
        self.conn.commit()
        self.conn.execute("VACUUM")
        self.report(time.time() - started)

    def report(self, elapsed: float) -> None:
        try:
            import pandas as pd

            df = pd.DataFrame(
                self.sheet_log, columns=["Лист", "Строк", "Обработано", "Льгот", "Комментарий"]
            )
            log("\n" + df.to_string(index=False))
        except Exception:  # pandas опционален для отчёта
            for row in self.sheet_log:
                log("   " + " | ".join(str(x) for x in row))

        meta = dict(self.conn.execute("SELECT key, value FROM meta").fetchall())
        log("\nИтог:")
        for key in ("universities", "programs", "benefits", "benefits_bvi", "benefits_sto",
                    "olympiads", "profiles", "links", "keywords"):
            log(f"   {key:14s}: {meta.get(key)}")
        top = self.conn.execute(
            """SELECT o.short_name, o.mentions, o.uni_count,
                      (SELECT COUNT(*) FROM olympiad_profiles pr WHERE pr.olympiad_id = o.id)
               FROM olympiads o ORDER BY o.mentions DESC LIMIT 12"""
        ).fetchall()
        log("\nТоп олимпиад по числу связей:")
        for name, mentions, unis, profiles in top:
            log(f"   {mentions:6d}  {unis:3d} вуз(ов)  {profiles:3d} профил.  {name}")
        log(f"\nГотово за {elapsed:.1f} c -> {os.path.abspath(self.db_path)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Импорт XLSX с льготами олимпиадников в SQLite")
    parser.add_argument("--xlsx", default=os.environ.get("XLSX_PATH", DEFAULT_XLSX))
    parser.add_argument("--db", default=os.environ.get("DB_PATH", DEFAULT_DB))
    args = parser.parse_args()

    if not os.path.exists(args.xlsx):
        log(f"Файл не найден: {args.xlsx}")
        return 1
    Ingestor(args.xlsx, args.db).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
