"""
Парсер XLSX «Олимпиады: БВИ и 100 баллов» -> нормализованная база PostgreSQL.

Запуск (схема должна быть создана миграциями: `alembic upgrade head`):
    olymp-ingest                                  # data/Olimpiady_BVI_100ballov.xlsx -> OLYMP_DATABASE_URL
    olymp-ingest --xlsx путь/к/файлу.xlsx --database-url postgresql+psycopg://...
    olymp-ingest --if-empty                       # собрать, только если база ещё пустая

Сборка идёт одной транзакцией: таблицы с данными очищаются и наполняются заново,
поэтому API до коммита видит прежнюю версию данных.

Что делает:
  1. Читает лист «База» (сводные правила по вузам и направлениям).
  2. Читает 15 подробных листов (ВШЭ, РЭУ, МИФИ, Бауманка, Финуниверситет,
     КФУ, УрФУ, ЦУ, Иннополис, Пирогова, ...) — каждый своим адаптером.
  3. Схлопывает ~450 грязных написаний названий олимпиад в канонический
     справочник (olympiads + olympiad_aliases).
  4. Строит связи «льгота ↔ олимпиада» (benefit_olympiads) — по колонке
     подробных листов и по тексту условий из «Базы».
  5. Вытаскивает ключевые слова (уровень, победитель/призёр, класс, порог ЕГЭ,
     предметы) в benefit_keywords и наполняет полнотекстовый индекс (tsvector).

Порядок обхода строк везде задан явно (ORDER BY id): от него зависят склейка
дублей и профилей, и результат должен быть одинаковым при каждой сборке.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
import psycopg
from olymp_db.models import DATA_TABLES
from olymp_db.session import database_url, psycopg_dsn
from olymp_domain.ege import parse_ege_requirement
from olymp_domain.olympiad_seeds import JUNK_KEYS, SEEDS
from olymp_domain.textutils import (
    SUBJECT_LIST_ALIASES,
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

from .extra_points import load_extra_points
from .olympiad_cards import CARDS_FILE, load_olympiad_cards
from .tables import clear_tables
from .tls import is_web_url
from .university_pages import PAGES

REPO = Path(__file__).resolve().parents[4]
DATA_DIR = Path(os.environ.get("OLYMP_DATA_DIR", REPO / "data"))
DEFAULT_XLSX = str(DATA_DIR / "Olimpiady_BVI_100ballov.xlsx")
SOURCES_CACHE = os.environ.get("SOURCES_CACHE", str(DATA_DIR / "university_documents.json"))

BVI = "БВИ"
STO = "100 баллов"
SPECIAL = "Особое право (БВИ/100)"
FASTTRACK = "Фаст-трек"
EXTRA_POINTS = "ИД (доп. баллы)"

SHEET_BASE = "База"

# Приложение 2 «Особые права… НИУ ВШЭ (Москва) 2026» — проверенная рабочая ссылка
HSE_SOURCE = (
    "Приложение 2 «Особые права при приёме… НИУ ВШЭ (г. Москва) 2026» — "
    "https://ba.hse.ru/mirror/pubs/share/1170753560"
)

# лист -> индекс колонки с названием олимпиады (для сбора справочника)
OLYMPIAD_COLUMNS: dict[str, int] = {
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
OFFICIAL_SOURCES: dict[str, dict[str, tuple[str, str]]] = {
    "итмо": {
        "БВИ": (
            "Приложение 5: олимпиады РСОШ, дающие БВИ (2026)",
            "https://abit.itmo.ru/file_storage/file/pages/82/rsosh_bvi_2026.pdf",
        ),
        "100 баллов": (
            "Приложение 5: олимпиады РСОШ на 100 баллов (2026)",
            "https://abit.itmo.ru/file_storage/file/pages/82/rsosh_100_2026.pdf",
        ),
        "*": (
            "Приложение 5: перечень олимпиад ИТМО (2026)",
            "https://abit.itmo.ru/file_storage/file/pages/82/rsosh_bvi_2026.pdf",
        ),
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
    "а": "астрономия",
    "б": "биология",
    "г": "география",
    "и": "история",
    "ин": "иностранный язык",
    "ия": "иностранный язык",
    "инф": "информатика",
    "л": "литература",
    "м": "математика",
    "о": "обществознание",
    "ря": "русский язык",
    "т": "труд (технология)",
    "ф": "физика",
    "х": "химия",
    "э": "экология",
    "эк": "экономика",
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
    aliases: set[str] = field(default_factory=set)
    squash_keys: set[str] = field(default_factory=set)
    mentions: int = 0
    db_id: int = 0


class OlympiadCatalog:
    """Схлопывает грязные варианты написания в канонические олимпиады."""

    def __init__(self) -> None:
        self.items: list[CanonicalOlympiad] = []
        self._by_seed: dict[int, CanonicalOlympiad] = {}

    # -- сбор -------------------------------------------------------------
    def harvest(self, wb) -> dict[str, Counter]:
        raw: dict[str, Counter] = defaultdict(Counter)
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

        assigned: dict[str, CanonicalOlympiad] = {}

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
        own: dict[str, CanonicalOlympiad] = {}
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
        seen_names: set[str] = set()
        for item in self.items:
            base = item.canonical_name
            n = 2
            while item.canonical_name in seen_names:
                item.canonical_name = f"{base} ({n})"
                n += 1
            seen_names.add(item.canonical_name)

    def add_international(self, wb) -> list[tuple[CanonicalOlympiad, str]]:
        """Лист «ВШЭ международные»: международные олимпиады + краткие коды."""
        out: list[tuple[CanonicalOlympiad, str]] = []
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
    def _lookup_by_key(self, key: str) -> CanonicalOlympiad | None:
        for item in self.items:
            if key in item.squash_keys:
                return item
        return None

    def _match_seed(self, key: str) -> int | None:
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
        raw: dict[str, Counter],
        assigned: dict[str, CanonicalOlympiad],
        own: dict[str, CanonicalOlympiad],
        totals: dict[str, int],
    ) -> CanonicalOlympiad | None:
        """Обрывок «...школьников Уральского...» приклеиваем к полному названию."""
        if len(key) < 12:
            return None
        candidates: list[tuple[int, CanonicalOlympiad]] = []
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
        def score(item: tuple[str, int]) -> tuple[int, int, int]:
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
# порядковый номер программы в списке ВШЭ: «№24. Экономика (38.03.01)» в «Базе»,
# а в подробных листах та же программа называется просто «Экономика»
RE_LIST_NUMBER = re.compile(r"^\s*№\s*\d+\s*[.)]?\s*")
# «Игры (по направлению 09.03.04 Программная инженерия)» — название программы до скобки
RE_BY_DIRECTION = re.compile(r"\s*\(\s*по\s+направлени\w*\s.*$", re.IGNORECASE)


def program_keys(name: str, code: str = "", profile: str = "") -> list[str]:
    """Ключи, по которым строка «Базы» и строка подробного листа считаются одной программой."""
    keys: list[str] = []
    text = clean_text(name)
    codes = extract_codes(text) or ([code] if code else [])
    codes = sorted({c for c in codes if c})
    name_wo_codes = squash(re.sub(r"\d{2}\.\d{2}\.\d{2}", " ", text))
    # без номера в списке и без «(по направлению …)»: так программу называют подробные листы.
    # Только вместе с кодом: одно название бывает у программ с разными кодами
    bare = RE_BY_DIRECTION.sub("", RE_LIST_NUMBER.sub("", text))
    bare_key = squash(re.sub(r"\d{2}\.\d{2}\.\d{2}", " ", bare))
    profile_key = squash(profile)

    if bare_key and codes:
        keys.append("nc:" + bare_key + "|" + ",".join(codes))
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
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn
        self._keys: dict[tuple[int, str], int] = {}
        # ключ «c:<код>» -> все программы вуза с этим кодом (D2): по одному коду программу
        # можно узнать, только если она единственная, иначе склеятся разные программы
        self._by_code: dict[tuple[int, str], list[int]] = defaultdict(list)
        self._codes: dict[int, set[str]] = {}  # коды созданных программ
        self._order: dict[int, int] = defaultdict(int)
        # (note, source_title, source_url) созданных программ: чтобы не перечитывать их из БД
        self._info: dict[int, list[str]] = {}

    def get_or_create(
        self,
        university_id: int,
        name: str,
        code: str = "",
        profile: str = "",
        note: str = "",
        source_url: str = "",
        source_sheet: str = "",
        match_by_code: bool = True,
    ) -> int:
        """
        Находит программу вуза по любому ключу или создаёт новую. `match_by_code=False` —
        для «Базы», где у каждой строки своя программа: одинаковый код (у ВШЭ — десятки
        программ на одном коде) не повод склеивать строки.
        """
        name = clean_text(name) or "Без названия"
        keys = program_keys(name, code, profile)
        incoming = set(extract_codes(name) or extract_codes(code) or ([code] if code else []))
        for key in keys:
            if key.startswith("c:"):
                same_code = self._by_code.get((university_id, key), [])
                pid = same_code[0] if match_by_code and len(same_code) == 1 else None
            else:
                pid = self._keys.get((university_id, key))
                # одно и то же название при разных кодах — разные программы
                # (ВШЭ: «Разработка игр и цифровых продуктов» есть и на 09.03.04, и на 54.03.01)
                if pid is not None and key[:2] in ("n:", "np") and incoming:
                    known = self._codes.get(pid, set())
                    if known and known != incoming:
                        pid = None
            if pid is not None:
                self._enrich(pid, note, source_url)
                return pid

        pid = self._truncated_name_match(university_id, keys, incoming) if match_by_code else None
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
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (
                university_id,
                name,
                clean_text(profile),
                ", ".join(sorted(set(codes))),
                clean_text(note),
                source_title,
                source_link,
                source_sheet,
                self._order[university_id],
            ),
        )
        pid = int(cur.fetchone()[0])
        self._codes[pid] = incoming
        self._info[pid] = [clean_text(note), source_title, source_link]
        for key in keys:
            if key.startswith("c:"):
                self._by_code[(university_id, key)].append(pid)
            else:
                self._keys.setdefault((university_id, key), pid)
        return pid

    def _truncated_name_match(self, university_id: int, keys: list[str], incoming: set[str]):
        """
        В подробных листах длинные названия бывают обрезаны (КФУ: «… (профиль: Иностранный
        (английский) язык и второй иностранный я»). Обрезок узнаём по началу названия, но только
        если ему подходит ровно одна программа вуза с тем же кодом.
        """
        stem = next((k[2:] for k in keys if k.startswith("n:")), "")
        if len(stem) < 60:
            return None
        found = {
            pid
            for (uid, key), pid in self._keys.items()
            if uid == university_id
            and key.startswith("n:")
            and key[2:] != stem
            and key[2:].startswith(stem)
            and (not incoming or not self._codes.get(pid) or self._codes[pid] == incoming)
        }
        return found.pop() if len(found) == 1 else None

    def _enrich(self, program_id: int, note: str, source_url: str) -> None:
        """Подробный лист может дать источник/примечание там, где «База» промолчала."""
        if not note and not source_url:
            return
        row = self._info[program_id]
        title, link = split_source(source_url)
        values = [row[0] or clean_text(note), row[1] or title, row[2] or link]
        if values == row:
            return
        self._info[program_id] = values
        self.conn.execute(
            "UPDATE programs SET note=%s, source_title=%s, source_url=%s WHERE id=%s",
            (*values, program_id),
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
    olympiad_id: int = 0  # если олимпиада уже определена — не ищем по названию
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
    agg: dict[tuple[str, str, str, str, str], dict[str, set[str]]] = {}
    for row in rows:
        olympiad = clean_name(cell(row, 0))
        benefit = cell(row, 2)
        direction = cell(row, 4)
        if not olympiad or benefit not in (BVI, STO) or not direction:
            continue
        key = (cell(row, 3), direction, olympiad, cell(row, 5), benefit)
        bucket = agg.setdefault(
            key, {"years": set(), "subjects": set(), "scores": set(), "profiles": set()}
        )
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
            conditions=join_parts(
                olympiad,
                f"профиль: {profile}" if profile else "",
                f"подтверждение ЕГЭ: {subjects}" if subjects else "",
            ),
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
                    conditions=join_parts(
                        olympiad,
                        f"профиль: {profile}" if profile else "",
                        f"уровень {level}" if level else "",
                        "победители и призёры",
                    ),
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
                conditions=join_parts(
                    olympiad,
                    f"профиль: {profile}" if profile else "",
                    f"уровень {level}" if level else "",
                    role,
                ),
                note=(
                    "БВИ только на программы кафедр секции"
                    if "кафедр" in winners
                    else "Подтверждение ЕГЭ ≥75 по профильному предмету"
                ),
                **base,
            )
        if gives_winners and not gives_prizers:
            yield DetailRow(
                benefit_type=STO,
                winner_role="призёры",
                conditions=join_parts(
                    olympiad,
                    f"профиль: {profile}" if profile else "",
                    f"уровень {level}" if level else "",
                    "призёры (БВИ не даётся) — 100 баллов по предмету олимпиады",
                ),
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
                conditions=join_parts(
                    olympiad,
                    f"профиль: {profile}" if profile else "",
                    f"уровень {level}" if level else "",
                    f"предмет группы: {subject}",
                ),
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
        conditions = join_parts(
            olympiad,
            f"профиль: {profile}" if profile else "",
            f"уровень {level}" if level else "",
            "победители и призёры",
        )
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
                yield DetailRow(
                    program_name=f"{code} {name}".strip(),
                    code=code,
                    confirm_subject=", ".join(vi_subjects),
                    **common,
                )
        else:
            for subject in vi_subjects or ["профильный предмет"]:
                yield DetailRow(
                    program_name=f"Все направления с ВИ по предмету «{subject}»",
                    confirm_subject=subject,
                    **common,
                )


def parse_code_names(text: str) -> list[tuple[str, str]]:
    """«07.03.01 Архитектура 44.03.04 Проф. обучение» -> [(код, название), ...]"""
    parts = re.split(r"(\d{2}\.\d{2}\.\d{2})", clean_text(text))
    out: list[tuple[str, str]] = []
    for i in range(1, len(parts), 2):
        code = parts[i]
        name = clean_text(parts[i + 1] if i + 1 < len(parts) else "")
        out.append((code, name.strip(" ,;.")[:120]))
    return out


def adapt_urfu(rows: Iterable[Sequence], legend: dict[str, str]) -> Iterator[DetailRow]:
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
        base = dict(
            university="Уральский федеральный университет (УрФУ)",
            program_name=program,
            code=code,
            source_url=url,
        )
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


def decode_codes(value: str, legend: dict[str, str]) -> str:
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
            conditions=join_parts(
                olympiad,
                f"профиль: {profile}" if profile else "",
                f"уровень {level}" if level else "",
                f"ВИ ЦУ: {subject}" if subject else "",
            ),
            note="Фаст-трек грантового конкурса: размер гранта определяется по собеседованию",
            source_url="https://cu.ru/olympiad",
        )


def adapt_innopolis(rows: Iterable[Sequence]) -> Iterator[DetailRow]:
    programs = [
        ("09.03.01", "09.03.01 Информатика и вычислительная техника"),
        ("15.03.06", "15.03.06 Робототехника и мехатроника"),
    ]
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
                conditions=join_parts(
                    olympiad,
                    f"профиль: {profile}" if profile else "",
                    f"уровень {level}" if level else "",
                    f"ВИ: {subject}" if subject else "",
                ),
                note="Какое именно право (БВИ или 100 баллов) применяется — определяют правила "
                "приёма университета; подтверждение ЕГЭ ≥75",
                source_url="https://innopolis.university/sveden/apply/",
            )


def adapt_pirogov(rows: Iterable[Sequence]) -> Iterator[DetailRow]:
    """Пирогова: 812 строк по годам -> агрегируем по (олимпиада, профиль, уровень, предмет)."""
    agg: dict[tuple[str, str, str, str, str], dict[str, set[str]]] = {}
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
                conditions=join_parts(
                    olympiad,
                    f"профиль: {profile}" if profile else "",
                    f"уровень {level}" if level else "",
                    f"профилирующий предмет: {bvi_subject}",
                ),
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
                conditions=join_parts(
                    olympiad,
                    f"профиль: {profile}" if profile else "",
                    f"уровень {level}" if level else "",
                    f"100 баллов по предмету: {subject}",
                ),
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
            conditions=join_parts(
                event,
                unit,
                f"предмет: {subject}" if subject else "",
                cell(row, 4) or "+4 балла к сумме (ИД)",
            ),
            note=f"Мероприятие УрФУ ({unit}); предмет должен входить в ВИ направления",
            source_url="https://urfu.ru/ru/applicant/",
        )


# ==========================================================================
#  основной конвейер
# ==========================================================================


class Ingestor:
    def __init__(self, xlsx_path: str, database_url: str | None = None) -> None:
        self.xlsx_path = xlsx_path
        self.database_url = database_url
        self.conn: psycopg.Connection
        self.catalog = OlympiadCatalog()
        self.matcher = OlympiadMatcher()
        self.programs: ProgramRegistry
        self.universities: dict[str, int] = {}
        self.uni_squash: dict[str, int] = {}
        self.olympiad_ids: dict[str, int] = {}  # squash key -> olympiad id
        # короткие сокращения (ПВГ, ЮМШ, МОШ, НТО): в поиске по тексту их нет, но в списке
        # точных названий (ИТМО) они однозначны
        self.short_aliases: dict[str, int] = {}
        self.olympiad_names: dict[int, str] = {}  # olympiad id -> короткое название
        self.olympiad_kinds: dict[int, str] = {}  # olympiad id -> rsosh | vsosh | international
        self.profile_ids: dict[tuple[int, str], int] = {}  # (olympiad_id, ключ) -> profile id
        self.seen_rows: dict[tuple, int] = {}  # ключ строки таблицы -> benefit id
        # id льгот выдаём сами (таблица очищена, нумерация с 1, удалений нет): вставки
        # не ждут ответа сервера и уходят пачками в режиме pipeline
        self.last_benefit_id = 0
        self.benefit_years: dict[int, str] = {}  # benefit id -> годы дипломов
        self.stats: Counter = Counter()
        self.sheet_log: list[tuple[str, int, int, int, str]] = []

    # -- инфраструктура ---------------------------------------------------
    def connect(self) -> None:
        """Одна транзакция на всю сборку: таблицы с данными очищаются и наполняются заново."""
        self.conn = psycopg.connect(psycopg_dsn(self.database_url))
        missing = [
            t
            for t in DATA_TABLES
            if self.conn.execute("SELECT to_regclass(%s)", (f"public.{t}",)).fetchone()[0] is None
        ]
        if missing:
            self.conn.close()
            raise SystemExit(
                "В базе нет таблиц "
                + ", ".join(missing)
                + ". Сначала примените миграции: cd packages/db && alembic upgrade head"
            )
        # DELETE, а не TRUNCATE: API до коммита читает прежние данные, а не ждёт (tables.py)
        clear_tables(self.conn, DATA_TABLES)
        self.programs = ProgramRegistry(self.conn)

    def executemany(self, sql: str, params: Iterable[Sequence]) -> None:
        with self.conn.cursor() as cur:
            cur.executemany(sql, list(params))

    def run(self) -> None:
        started = time.time()
        log(f"[1/7] Читаю {self.xlsx_path}")
        wb = openpyxl.load_workbook(self.xlsx_path, read_only=True, data_only=True)
        log(f"      листов: {len(wb.sheetnames)} -> {', '.join(wb.sheetnames)}")

        self.connect()
        try:
            self._build(wb, started)
        except BaseException:
            self.conn.rollback()
            raise
        finally:
            wb.close()
            self.conn.close()

    def _build(self, wb, started: float) -> None:
        # Массовые вставки идут в режиме pipeline: запросы, результат которых сразу не
        # нужен, отправляются пачкой, а не по одному с ожиданием ответа сервера.
        log("[2/7] Собираю справочник олимпиад")
        self.catalog.build(wb)
        international = self.catalog.add_international(wb)
        with self.conn.pipeline():
            self.save_catalog()
        log(f"      канонических олимпиад: {len(self.catalog.items)}")

        log("[3/7] Лист «База»")
        with self.conn.pipeline():
            self.ingest_base(wb)

        log("[4/7] Подробные листы")
        with self.conn.pipeline():
            self.ingest_details(wb)
            self.ingest_international(international)
        self.fill_source_fallbacks()

        log("[5/7] Разбор текстовых правил и ключевые слова")
        with self.conn.pipeline():
            self.expand_summaries()
        self.update_counters()
        merged = self.merge_profile_fragments()
        if merged:
            log(f"      склеено обрывков профилей: {merged}")
            self.update_counters()
        self.profile_levels()
        with self.conn.pipeline():
            self.expand_profile_rules()
        # id льгот выдавали сами — сдвигаем последовательность, чтобы вставки после сборки
        # (если они когда-нибудь понадобятся) не столкнулись с занятыми id
        self.conn.execute(
            "SELECT setval(pg_get_serial_sequence('benefits', 'id'), %s + 1, false)",
            (self.last_benefit_id,),
        )
        self.apply_university_pages()
        self.apply_official_sources()
        merged = self.merge_profile_fragments()
        if merged:
            log(f"      склеено обрывков профилей: {merged}")
        self.extract_keywords()
        parsed, total = self.parse_ege_requirements()
        log(f"      пороги ЕГЭ разобраны: {parsed} из {total} непустых строк")

        log("[6/7] Полнотекстовый индекс")
        self.build_fts()

        cards = load_olympiad_cards(self.conn, DATA_DIR)
        log(f"      карточки олимпиад: {cards['cards']}, треков {cards['tracks']}")

        extra = load_extra_points(self.conn, DATA_DIR)
        log(f"      баллы за ИД: правил {extra['rules']}, лимитов {extra['limits']}")

        log("[7/7] Статистика")
        self.finalize(started)

    def parse_ege_requirements(self) -> tuple[int, int]:
        """confirm_subjects и min_ege_score из текста (T-031). Различных пар текста — пара сотен,
        поэтому обновляем по паре, а не по строке."""
        pairs = self.conn.execute(
            """SELECT confirm_subject, min_ege, count(*) FROM benefits
               GROUP BY confirm_subject, min_ege"""
        ).fetchall()
        parsed = total = 0
        with self.conn.cursor() as cur:
            for subject, minimum, count in pairs:
                requirement = parse_ege_requirement(subject, minimum)
                if (subject or "").strip() or (minimum or "").strip():
                    total += count
                    parsed += count if requirement is not None else 0
                if requirement is None:
                    continue  # не разобрано: колонки остаются NULL
                cur.execute(
                    """UPDATE benefits SET confirm_subjects = %s, min_ege_score = %s
                       WHERE confirm_subject = %s AND min_ege = %s""",
                    (list(requirement.subjects), requirement.min_score, subject, minimum),
                )
        return parsed, total

    # -- справочник -------------------------------------------------------
    def save_catalog(self) -> None:
        for item in self.catalog.items:
            cur = self.conn.execute(
                """INSERT INTO olympiads (canonical_name, short_name, squash_key, kind,
                                          is_featured, mentions)
                   VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                (
                    item.canonical_name,
                    item.short_name or item.canonical_name[:40],
                    sorted(item.squash_keys)[0]
                    if item.squash_keys
                    else squash(item.canonical_name),
                    item.kind,
                    int(item.featured),
                    item.mentions,
                ),
            )
            item.db_id = int(cur.fetchone()[0])
            self.olympiad_names[item.db_id] = item.short_name or item.canonical_name
            self.olympiad_kinds[item.db_id] = item.kind
            aliases = set(item.aliases) | {item.canonical_name, item.short_name}
            # sorted: порядок множества строк в Python меняется от запуска к запуску,
            # а при одинаковом ключе в базу попадает первое написание
            for alias in sorted(aliases):
                alias = clean_text(alias)
                if not alias:
                    continue
                sq = squash(alias)
                if len(sq) < 2:
                    continue
                self.conn.execute(
                    """INSERT INTO olympiad_aliases (olympiad_id, alias, squash_alias, is_generic)
                       VALUES (%s,%s,%s,%s) ON CONFLICT (olympiad_id, squash_alias) DO NOTHING""",
                    (item.db_id, alias, sq, int(len(sq) < 16)),
                )
                self.matcher.add(item.db_id, alias, is_generic=len(sq) < 16)
                # одно сокращение у двух олимпиад — неоднозначно, не используем (-1)
                if len(sq) < 4 and self.short_aliases.setdefault(sq, item.db_id) != item.db_id:
                    self.short_aliases[sq] = -1
            for key in item.squash_keys:
                self.olympiad_ids[key] = item.db_id

    def olympiad_id_for(self, name: str) -> int | None:
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
                    "UPDATE universities SET region=%s, region_group=%s, city=%s"
                    " WHERE id=%s AND region=''",
                    (region, self.region_group(region), self.city_for(name, region), uid),
                )
            return uid
        key = squash(name)
        if key in self.uni_squash:
            return self.uni_squash[key]
        note = next((text for hint, text in UNIVERSITY_NOTES.items() if hint in key), "")
        cur = self.conn.execute(
            "INSERT INTO universities (name, short_name, region, city, note, region_group)"
            " VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (
                name,
                self.short_university(name),
                clean_text(region),
                self.city_for(name, region),
                note,
                self.region_group(region),
            ),
        )
        uid = int(cur.fetchone()[0])
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
                uid,
                faculty or profile or "Общие правила",
                profile=profile,
                note=note,
                source_url=source,
                source_sheet=SHEET_BASE,
                match_by_code=False,
            )
            for idx, benefit_type in ((4, BVI), (5, STO)):
                text = cell(row, idx)
                if not text or text in ("—", "-", "–"):
                    continue
                self.insert_benefit(
                    DetailRow(
                        university=university,
                        program_name=faculty,
                        benefit_type=benefit_type,
                        conditions=text,
                        note=note,
                        source_url=source,
                    ),
                    program_id=pid,
                    layer="summary",
                    source_sheet=SHEET_BASE,
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
                    uid,
                    detail.program_name,
                    code=detail.code,
                    profile=detail.profile_name,
                    source_url=detail.source_url,
                    source_sheet=sheet,
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
        best: dict[int, tuple[str, str]] = {}
        # Как в прототипе на SQLite: название документа берётся у первой строки группы,
        # а при равной частоте побеждает ссылка, идущая позже по алфавиту.
        rows = self.conn.execute(
            """SELECT university_id, (array_agg(source_title ORDER BY id))[1],
                      source_url, COUNT(*) AS cnt
               FROM programs WHERE source_url <> ''
               GROUP BY university_id, source_url
               ORDER BY university_id, cnt DESC, source_url DESC"""
        ).fetchall()
        for university_id, title, url, _ in rows:
            best.setdefault(university_id, (title, url))

        self.executemany(
            "UPDATE universities SET site_url=%s WHERE id=%s",
            [(url, uid) for uid, (_, url) in best.items()],
        )
        filled = 0
        for university_id, (title, url) in best.items():
            cur = self.conn.execute(
                """UPDATE programs SET source_title = CASE WHEN source_title = '' THEN %s
                                                           ELSE source_title END,
                                       source_url = %s
                   WHERE university_id = %s AND source_url = ''""",
                (title, url, university_id),
            )
            filled += cur.rowcount
        # вузы, у которых в таблице нет ни одной ссылки — ведём на приёмную комиссию
        from_catalog = 0
        for uid, name in self.conn.execute(
            """SELECT u.id, u.name FROM universities u
               WHERE EXISTS (SELECT 1 FROM programs p
                             WHERE p.university_id = u.id AND p.source_url = '')
               ORDER BY u.id"""
        ).fetchall():
            key = squash(name)
            hit = next(
                ((t, url) for part, (t, url) in UNIVERSITY_SOURCES.items() if part in key), None
            )
            if not hit:
                continue
            title, url = hit
            cur = self.conn.execute(
                """UPDATE programs SET source_title = CASE WHEN source_title = '' THEN %s
                                                           ELSE source_title END,
                                       source_url = %s
                   WHERE university_id = %s AND source_url = ''""",
                (title, url, uid),
            )
            from_catalog += cur.rowcount
            self.conn.execute(
                "UPDATE universities SET site_url=%s WHERE id=%s AND site_url=''", (url, uid)
            )

        missing = self.conn.execute(
            "SELECT COUNT(*) FROM programs WHERE source_url = ''"
        ).fetchone()[0]
        log(
            f"      источники: подставлено по вузу {filled}, по справочнику приёмных комиссий "
            f"{from_catalog}, осталось без ссылки {missing}"
        )

    def apply_university_pages(self) -> None:
        """
        Проставляет вузам стабильную страницу раздела с документами и подтягивает
        файлы, найденные на ней скриптом refresh_sources.py (кэш в data/).
        """
        cache: dict[str, dict] = {}
        if os.path.exists(SOURCES_CACHE):
            try:
                with open(SOURCES_CACHE, encoding="utf-8") as fh:
                    cache = json.load(fh)
            except Exception as exc:
                log(f"      ! кэш документов не прочитан: {exc}")

        pages = documents = 0
        stamp = time.strftime("%Y-%m-%d")
        # в прототипе этот запрос шёл по индексу на name — вузы обходились по алфавиту
        for uid, name in self.conn.execute(
            "SELECT id, name FROM universities ORDER BY name"
        ).fetchall():
            key = squash(name)
            page = next((p for part, p in PAGES.items() if part in key), None)
            if page:
                self.conn.execute(
                    "UPDATE universities SET docs_url=%s, docs_title=%s WHERE id=%s",
                    (page.url, page.title, uid),
                )
                pages += 1
            entry = cache.get(name)
            if not entry:
                continue
            for doc in entry.get("documents", []):
                if not is_web_url(doc.get("url", "")):
                    continue  # в кэш могла попасть javascript:/data:-ссылка (T-078)
                # повтор ссылки заменяет прежнюю запись и уходит в конец списка
                self.conn.execute(
                    "DELETE FROM university_documents WHERE university_id=%s AND url=%s",
                    (uid, doc["url"]),
                )
                self.conn.execute(
                    """INSERT INTO university_documents (university_id, title, url, checked_at)
                       VALUES (%s,%s,%s,%s)""",
                    (uid, doc.get("title", "Документ"), doc["url"], entry.get("checked_at", stamp)),
                )
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
        # в прототипе этот запрос шёл по индексу на name — вузы обходились по алфавиту
        for uid, name in self.conn.execute(
            "SELECT id, name FROM universities ORDER BY name"
        ).fetchall():
            key = squash(name)
            docs = next((d for part, d in OFFICIAL_SOURCES.items() if part in key), None)
            if not docs:
                continue
            for benefit_type, (title, url) in docs.items():
                if benefit_type == "*":
                    continue
                cur = self.conn.execute(
                    """UPDATE benefits SET source_title=%s, source_url=%s
                       WHERE benefit_type=%s AND program_id IN
                             (SELECT id FROM programs WHERE university_id=%s)""",
                    (title, url, benefit_type, uid),
                )
                overridden += cur.rowcount
            title, url = docs.get("*", ("", ""))
            if url:
                self.conn.execute(
                    "UPDATE programs SET source_title=%s, source_url=%s WHERE university_id=%s",
                    (title, url, uid),
                )
                self.conn.execute("UPDATE universities SET site_url=%s WHERE id=%s", (url, uid))
        log(f"      прямых документов подставлено: {overridden}")

    def read_urfu_legend(self, wb) -> dict[str, str]:
        legend: dict[str, str] = {}
        if "УрФУ легенда" not in wb.sheetnames:
            return legend
        for row in wb["УрФУ легенда"].iter_rows(min_row=2, values_only=True):
            code, profile = cell(row, 0), cell(row, 1)
            if code and profile:
                legend[code.lower()] = profile
        return legend

    def ingest_international(self, pairs: list[tuple[CanonicalOlympiad, str]]) -> None:
        if not pairs:
            return
        uid = self.university_id("НИУ ВШЭ (Москва)", "Москва")
        pid = self.programs.get_or_create(
            uid,
            "Международные олимпиады: БВИ членам сборных РФ",
            note="Приложение 3 НИУ ВШЭ: члены сборных команд РФ на международных олимпиадах "
            "получают БВИ на направления, соответствующие предмету олимпиады",
            source_url=HSE_SOURCE,
            source_sheet="ВШЭ международные",
        )
        count = 0
        for item, subject in pairs:
            self.insert_benefit(
                DetailRow(
                    university="НИУ ВШЭ (Москва)",
                    program_name="Международные олимпиады: БВИ членам сборных РФ",
                    benefit_type=BVI,
                    olympiad_name=item.canonical_name,
                    olympiad_subject=subject,
                    winner_role="члены сборных команд РФ",
                    conditions=f"{item.canonical_name} ({item.short_name}) — предмет соответствия: {subject}",
                    note="БВИ по ч. 4 ст. 71 273-ФЗ — члены сборных команд РФ",
                ),
                program_id=pid,
                layer="detailed",
                source_sheet="ВШЭ международные",
            )
            count += 1
        self.stats["international"] = count
        log(f"      «ВШЭ международные»: {count} олимпиад -> БВИ членам сборных")

    # -- вставка льготы ---------------------------------------------------
    def insert_benefit(
        self, detail: DetailRow, program_id: int, layer: str, source_sheet: str
    ) -> int:
        # В исходных листах одна и та же строка иногда повторяется (артефакт вёрстки
        # PDF). Для таблиц это мусор, поэтому полностью идентичные строки пропускаем.
        # каноническая олимпиада: в источниках одна и та же олимпиада за разные годы
        # называется по-разному, поэтому в ключе строки должен быть id справочника
        olympiad_id = detail.olympiad_id or (
            self.olympiad_id_for(detail.olympiad_name) if detail.olympiad_name else 0
        )

        if layer in ("detailed", "derived"):
            key = (
                program_id,
                detail.benefit_type,
                olympiad_id or squash(detail.olympiad_name),
                squash(detail.olympiad_profile),
                squash(detail.olympiad_subject),
                detail.level,
                detail.winner_role,
                detail.grade,
                squash(detail.confirm_subject),
                detail.min_ege,
            )
            twin = self.seen_rows.get(key)
            if twin is not None:
                # строки-близнецы обычно отличаются только годом диплома — сливаем годы
                self.merge_years(twin, detail.years)
                self.stats["duplicates"] += 1
                return twin
            self.seen_rows[key] = 0  # id проставим после вставки

        source_title, source_link = split_source(detail.source_url)
        self.last_benefit_id += 1
        benefit_id = self.last_benefit_id
        self.conn.execute(
            """INSERT INTO benefits
               (id, program_id, benefit_type, raw_conditions_text, layer, olympiad_profile,
                olympiad_subject, level, winner_role, grade, confirm_subject, min_ege,
                award_subject, years, note, source_title, source_url, source_sheet)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                benefit_id,
                program_id,
                detail.benefit_type,
                detail.conditions or detail.olympiad_name,
                layer,
                detail.olympiad_profile,
                detail.olympiad_subject,
                detail.level,
                detail.winner_role,
                detail.grade,
                detail.confirm_subject,
                detail.min_ege,
                detail.award_subject,
                detail.years,
                detail.note,
                source_title,
                source_link,
                source_sheet,
            ),
        )
        self.benefit_years[benefit_id] = detail.years
        if layer in ("detailed", "derived"):
            self.seen_rows[key] = benefit_id
        self.stats["benefits"] += 1

        linked = False
        if olympiad_id:
            self.link(
                benefit_id,
                olympiad_id,
                detail.olympiad_profile,
                detail.level,
                detail.winner_role,
                "column",
            )
            linked = True
        if not linked:
            for hit in self.matcher.find(detail.conditions):
                self.link(
                    benefit_id,
                    hit.olympiad_id,
                    detail.olympiad_profile,
                    detail.level,
                    detail.winner_role,
                    "text",
                )
        return benefit_id

    def profile_id_for(self, olympiad_id: int, profile: str) -> int | None:
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
        created = self.conn.execute(
            """INSERT INTO olympiad_profiles (olympiad_id, name, squash_key) VALUES (%s,%s,%s)
               ON CONFLICT (olympiad_id, squash_key) DO NOTHING RETURNING id""",
            (olympiad_id, name, key),
        ).fetchone()
        profile_id = (
            int(created[0])
            if created
            else int(
                self.conn.execute(
                    "SELECT id FROM olympiad_profiles WHERE olympiad_id=%s AND squash_key=%s",
                    (olympiad_id, key),
                ).fetchone()[0]
            )
        )
        self.profile_ids[(olympiad_id, key)] = profile_id
        return profile_id

    def merge_years(self, benefit_id: int, years: str) -> None:
        """«2026» + «2023, 2024» -> «2023, 2024, 2026» в уже вставленной строке."""
        new = {y.strip() for y in clean_text(years).split(",") if y.strip()}
        if not new or not benefit_id:
            return
        current = {
            y.strip() for y in (self.benefit_years[benefit_id] or "").split(",") if y.strip()
        }
        if new <= current:
            return
        years = ", ".join(sorted(current | new))
        self.benefit_years[benefit_id] = years
        self.conn.execute("UPDATE benefits SET years=%s WHERE id=%s", (years, benefit_id))

    def link(
        self, benefit_id: int, olympiad_id: int, profile: str, level: str, role: str, via: str
    ) -> None:
        self.conn.execute(
            """INSERT INTO benefit_olympiads
               (benefit_id, olympiad_id, profile_id, profile, level, winner_role, matched_via)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (benefit_id, olympiad_id, profile, level) DO NOTHING""",
            (
                benefit_id,
                olympiad_id,
                self.profile_id_for(olympiad_id, profile),
                clean_profile(profile)[:300],
                clean_text(level),
                clean_text(role),
                via,
            ),
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
               FROM benefits b WHERE b.layer = 'summary' ORDER BY b.id"""
        ).fetchall()

        added = hidden = kept = 0
        for bid, program_id, btype, text, note, url, min_ege, detailed in rows:
            resolved = self.resolve_enumeration(text)
            if not resolved:
                kept += 1
                continue
            self.conn.execute("UPDATE benefits SET layer='raw' WHERE id=%s", (bid,))
            hidden += 1
            if detailed:
                continue  # подробный лист уже дал эти строки
            seen: set[tuple] = set()
            for olympiad_id, profile, subject, item in resolved:
                key = (olympiad_id, squash(profile), item.level, item.role, item.grade)
                if key in seen:
                    continue
                seen.add(key)
                name = self.olympiad_names.get(olympiad_id, item.name)
                detail = DetailRow(
                    university="",
                    program_name="",
                    benefit_type=btype,
                    olympiad_name=name,
                    olympiad_id=olympiad_id,
                    olympiad_profile=profile,
                    olympiad_subject=subject,
                    level=item.level,
                    winner_role=item.role,
                    grade=item.grade,
                    confirm_subject=subject,
                    min_ege=min_ege,
                    note=note,
                    source_url=url,
                    conditions=join_parts(
                        name,
                        f"профиль: {profile}" if profile else "",
                        f"уровень {item.level}" if item.level else "",
                        item.role,
                        item.grade,
                    ),
                )
                self.insert_benefit(
                    detail,
                    program_id=program_id,
                    layer="detailed",
                    source_sheet="База (разбор текста)",
                )
                added += 1
        self.stats["expanded"] = added
        log(
            f"      разобрано перечислений: +{added} строк, скрыто дублей текста: {hidden}, "
            f"осталось текстовых правил: {kept}"
        )

    # -- правила «любая олимпиада перечня по профилю X» ---------------------
    def expand_profile_rules(self) -> None:
        """
        Часть вузов (ИТМО, УрФУ, Горный) задаёт льготу профилем олимпиады, а не её
        названием: «любая олимпиада перечня I–III уровня по информатике», «все
        технологические профили (… мобильные приложения …) — БВИ». Раскрываем такие
        правила в конкретные пары «олимпиада + профиль» по справочнику профилей.
        """
        index = ProfileIndex()
        meta: dict[int, tuple[int, str, str]] = {}
        for pid, olympiad_id, name, level in self.conn.execute(
            "SELECT id, olympiad_id, name, level FROM olympiad_profiles WHERE mentions >= 2"
            " ORDER BY id"
        ).fetchall():
            index.add(pid, name)
            meta[pid] = (olympiad_id, name, level)

        sources = self.conn.execute(
            """SELECT b.id, b.program_id, b.benefit_type, b.raw_conditions_text, b.note,
                      b.source_url, b.min_ege, b.confirm_subject
               FROM benefits b
               WHERE b.layer IN ('summary', 'raw')
                  OR (b.layer = 'detailed'
                      AND NOT EXISTS (SELECT 1 FROM benefit_olympiads bo WHERE bo.benefit_id = b.id))
               -- порядок прототипа: сначала разобранные перечисления, потом текстовые
               -- правила, потом строки без олимпиады; от него зависят id выведенных строк
               ORDER BY CASE b.layer WHEN 'raw' THEN 0 WHEN 'summary' THEN 1 ELSE 2 END, b.id"""
        ).fetchall()

        seen_by_program: dict[tuple[int, str], set[tuple[int, int]]] = {}
        added = rules_used = 0
        for _bid, program_id, btype, text, _note, url, min_ege, confirm in sources:
            rules = parse_profile_rules(text)
            if not rules:
                continue
            key = (program_id, btype)
            if key not in seen_by_program:
                seen_by_program[key] = {
                    (row[0], row[1])
                    for row in self.conn.execute(
                        """SELECT bo.olympiad_id, bo.profile_id FROM benefit_olympiads bo
                           JOIN benefits b ON b.id = bo.benefit_id
                           WHERE b.program_id = %s AND b.benefit_type = %s
                             AND bo.profile_id IS NOT NULL""",
                        (program_id, btype),
                    )
                }
            seen = seen_by_program[key]
            produced = 0
            for rule in rules:
                # ВсОШ и так прописана отдельными строками в каждом листе —
                # раскрытие её «по профилю» дало бы только дубли
                if rule.scope == "vsosh":
                    continue
                rule_confirm = ", ".join(rule.confirm) or confirm
                # «НТО (все профили)» — все профили олимпиады из справочника
                whole = set()
                for name in rule.whole_olympiads:
                    whole.update(h.olympiad_id for h in self.matcher.find(name))
                    short = self.short_aliases.get(squash(name), -1)
                    if short > 0:
                        whole.add(short)
                candidates = [(token, index.find(token)) for token in rule.profiles]
                if whole:
                    candidates.append(
                        (
                            "",
                            [
                                pid
                                for pid, meta_item in sorted(meta.items())
                                if meta_item[0] in whole
                            ],
                        )
                    )
                for _token, profile_ids in candidates:
                    for profile_id in profile_ids:
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
                                university="",
                                program_name="",
                                benefit_type=btype,
                                olympiad_name=name,
                                olympiad_id=olympiad_id,
                                olympiad_profile=profile_name,
                                level=level,
                                winner_role=rule.role or "победители и призёры",
                                confirm_subject=rule_confirm,
                                min_ege=min_ege,
                                note="Правило вуза: любая олимпиада перечня с этим профилем",
                                source_url=url,
                                conditions=join_parts(
                                    name,
                                    f"профиль: {profile_name}",
                                    f"уровень {level}" if level else "",
                                ),
                            ),
                            program_id=program_id,
                            layer="derived",
                            source_sheet="Правило по профилю",
                        )
                        added += 1
                        produced += 1
                        if produced >= 300:  # защита от патологических правил
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
            if item.exact:
                alias = SUBJECT_LIST_ALIASES.get(squash(item.name), item.name)
                ids = [h.olympiad_id for h in self.matcher.find(alias)]
                short = self.short_aliases.get(squash(alias), -1)
                if not ids and short > 0:
                    ids = [short]
                for olympiad_id in ids:
                    out.append((olympiad_id, item.profile, "", item))
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
               FROM benefits WHERE layer <> 'derived' ORDER BY id"""
        ).fetchall()
        payload: list[tuple[int, str, str]] = []
        for bid, text, level, role, grade, min_ege, confirm, profile, subject in rows:
            found: set[tuple[str, str]] = set()
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
        self.executemany(
            """INSERT INTO benefit_keywords (benefit_id, kind, keyword) VALUES (%s,%s,%s)
               ON CONFLICT (benefit_id, kind, keyword) DO NOTHING""",
            payload,
        )
        self.stats["keywords"] = len(payload)
        log(f"      ключевых слов: {len(payload)}")

        self.update_counters()

    def profile_levels(self) -> None:
        """Преобладающий уровень пары «олимпиада + профиль» — из подробных листов.

        При равном числе упоминаний побеждает старший по записи уровень (III раньше II):
        так эту ничью разрешал прототип на SQLite.
        """
        rows = self.conn.execute(
            """SELECT profile_id, level, COUNT(*) AS cnt FROM benefit_olympiads
               WHERE profile_id IS NOT NULL AND level IN ('I','II','III')
               GROUP BY profile_id, level ORDER BY profile_id, cnt DESC, level DESC"""
        ).fetchall()
        best: dict[int, tuple[str, int]] = {}
        for profile_id, level, cnt in rows:
            if profile_id not in best or cnt > best[profile_id][1]:
                best[profile_id] = (level, cnt)
        self.executemany(
            "UPDATE olympiad_profiles SET level=%s WHERE id=%s",
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
        olympiad_ids = [
            r[0]
            for r in self.conn.execute(
                "SELECT olympiad_id FROM olympiad_profiles GROUP BY olympiad_id HAVING COUNT(*) > 1"
                " ORDER BY olympiad_id"
            ).fetchall()
        ]
        for olympiad_id in olympiad_ids:
            rows = self.conn.execute(
                "SELECT id, squash_key, mentions FROM olympiad_profiles WHERE olympiad_id=%s"
                " ORDER BY mentions DESC, id",
                (olympiad_id,),
            ).fetchall()
            alive = {pid: (key, mentions) for pid, key, mentions in rows}
            for pid, key, mentions in sorted(rows, key=lambda r: r[2]):
                if mentions > 3 or len(key) < 12 or pid not in alive:
                    continue
                parent = None
                for other_id, (other_key, other_mentions) in alive.items():
                    if other_id == pid or other_mentions <= mentions:
                        continue
                    common = os.path.commonprefix([key, other_key])
                    similar = key in other_key or other_key in key or len(common) >= 25
                    if similar and (parent is None or other_mentions > alive[parent][1]):
                        parent = other_id
                if parent is None:
                    continue
                self.conn.execute(
                    """UPDATE benefit_olympiads
                       SET profile_id = %s,
                           profile = (SELECT name FROM olympiad_profiles WHERE id = %s)
                       WHERE profile_id = %s""",
                    (parent, parent, pid),
                )
                self.conn.execute("DELETE FROM olympiad_profiles WHERE id=%s", (pid,))
                alive.pop(pid, None)
                merged += 1
        return merged

    # -- полнотекстовый индекс -------------------------------------------
    def build_fts(self) -> None:
        # одна запись на льготу: условия, направление, вуз, регион и названия олимпиад.
        # Конфигурация simple — только нижний регистр, без стемминга (как unicode61 в FTS5).
        cur = self.conn.execute(
            """INSERT INTO search_index (benefit_id, document)
               SELECT b.id, to_tsvector('simple', concat_ws(' ',
                          COALESCE((SELECT string_agg(o.canonical_name || ' ' || o.short_name, ' ')
                                    FROM benefit_olympiads bo
                                    JOIN olympiads o ON o.id = bo.olympiad_id
                                    WHERE bo.benefit_id = b.id), ''),
                          b.raw_conditions_text || ' ' || b.note || ' ' || b.olympiad_profile
                              || ' ' || b.olympiad_subject,
                          p.faculty_or_direction || ' ' || p.profile_name || ' ' || p.code,
                          u.name, u.region))
               FROM benefits b
               JOIN programs p ON p.id = b.program_id
               JOIN universities u ON u.id = p.university_id
               WHERE b.layer <> 'derived'"""
        )
        self.conn.execute("INSERT INTO meta (key, value) VALUES ('fts', 'on')")
        log(f"      проиндексировано записей: {cur.rowcount}")

    # -- финал ------------------------------------------------------------
    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            """INSERT INTO meta (key, value) VALUES (%s, %s)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            (key, value),
        )

    def finalize(self, started: float) -> None:
        self.executemany(
            "INSERT INTO ingest_log (sheet, rows_read, rows_ingested, benefits, comment)"
            " VALUES (%s,%s,%s,%s,%s)",
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
            "extra_rules": "SELECT COUNT(*) FROM individual_achievements",
            "extra_universities": "SELECT COUNT(DISTINCT university_id) FROM individual_achievements",
            "extra_limits": "SELECT COUNT(*) FROM individual_achievement_limits",
        }
        for key, sql in counts.items():
            value = self.conn.execute(sql).fetchone()[0]
            self.set_meta(key, str(value))
        self.set_meta("source_file", os.path.basename(self.xlsx_path))
        self.set_meta("build_fingerprint", build_fingerprint(self.xlsx_path))
        self.set_meta("built_at", time.strftime("%Y-%m-%d %H:%M:%S"))
        self.conn.commit()
        # свежая статистика для планировщика запросов
        self.conn.execute("ANALYZE")
        self.conn.commit()
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
        for key in (
            "universities",
            "programs",
            "benefits",
            "benefits_bvi",
            "benefits_sto",
            "olympiads",
            "profiles",
            "links",
            "keywords",
        ):
            log(f"   {key:14s}: {meta.get(key)}")
        top = self.conn.execute(
            """SELECT o.short_name, o.mentions, o.uni_count,
                      (SELECT COUNT(*) FROM olympiad_profiles pr WHERE pr.olympiad_id = o.id)
               FROM olympiads o ORDER BY o.mentions DESC, o.id LIMIT 12"""
        ).fetchall()
        log("\nТоп олимпиад по числу связей:")
        for name, mentions, unis, profiles in top:
            log(f"   {mentions:6d}  {unis:3d} вуз(ов)  {profiles:3d} профил.  {name}")
        log(f"\nГотово за {elapsed:.1f} c -> {self.conn.info.dbname}@{self.conn.info.host}")


def build_fingerprint(xlsx_path: str) -> str:
    """Отпечаток всего, от чего зависит результат сборки: исходные данные и код разбора.

    Меняется, если поменяли XLSX, кэш ссылок на документы вузов или код разбора (этот файл,
    нормализация текста, справочник олимпиад, страницы вузов). Тогда `--if-stale` пересоберёт базу.
    """
    import olymp_domain.ege as ege
    import olymp_domain.olympiad_cards as cards
    import olymp_domain.olympiad_seeds as seeds
    import olymp_domain.textutils as textutils

    from . import olympiad_cards, university_pages

    parts = [
        Path(xlsx_path),
        Path(SOURCES_CACHE),
        Path(__file__),
        Path(university_pages.__file__),
        Path(textutils.__file__),
        Path(seeds.__file__),
        DATA_DIR / CARDS_FILE,
        Path(olympiad_cards.__file__),
        Path(cards.__file__),
        Path(ege.__file__),
    ]
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.name.encode())
        digest.update(part.read_bytes() if part.exists() else b"-")
    return digest.hexdigest()[:16]


def is_current(url: str | None, xlsx_path: str) -> bool:
    """База собрана тем же кодом и теми же данными, что и сейчас (см. build_fingerprint)."""
    with psycopg.connect(psycopg_dsn(url)) as conn:
        if conn.execute("SELECT to_regclass('public.meta')").fetchone()[0] is None:
            return False
        row = conn.execute("SELECT value FROM meta WHERE key = 'build_fingerprint'").fetchone()
    return row is not None and row[0] == build_fingerprint(xlsx_path)


def has_data(url: str | None) -> bool:
    """В базе уже есть собранные данные (проверка для первого старта контейнера)."""
    with psycopg.connect(psycopg_dsn(url)) as conn:
        if conn.execute("SELECT to_regclass('public.meta')").fetchone()[0] is None:
            return False
        return conn.execute("SELECT 1 FROM meta WHERE key = 'built_at'").fetchone() is not None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Сборка базы PostgreSQL из XLSX с льготами олимпиадников"
    )
    parser.add_argument("--xlsx", default=os.environ.get("XLSX_PATH", DEFAULT_XLSX))
    parser.add_argument(
        "--database-url", default=database_url(), help="по умолчанию OLYMP_DATABASE_URL"
    )
    parser.add_argument(
        "--if-empty", action="store_true", help="ничего не делать, если база уже собрана"
    )
    parser.add_argument(
        "--if-stale",
        action="store_true",
        help="собрать, только если базы нет или изменились данные либо код разбора",
    )
    args = parser.parse_args()

    if not os.path.exists(args.xlsx):
        log(f"Файл не найден: {args.xlsx}")
        return 1
    if args.if_empty and has_data(args.database_url):
        log("База уже собрана — пропускаю (без --if-empty соберётся заново)")
        return 0
    if args.if_stale and is_current(args.database_url, args.xlsx):
        log("База собрана текущими данными и кодом разбора — пропускаю")
        return 0
    Ingestor(args.xlsx, args.database_url).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
