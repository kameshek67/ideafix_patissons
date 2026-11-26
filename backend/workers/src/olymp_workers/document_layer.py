"""Слой document: льготы, извлечённые из документов вузов, в сборке базы.

Источники — файлы data/extracted/*.json и таблица document_records (принятые оператором;
набор записей с тем же url заменяет файл). Слой накладывается на XLSX: строки документа
добавляются, а строка XLSX с тем же ключом (вуз, направление, олимпиада, профиль, тип льготы)
заменяется строкой документа — побеждает документ, его поля и источник.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg
from olymp_domain.extraction import ExtractionError, Record, load_dir, profile_key
from olymp_domain.textutils import clean_text

from .eval_extract import ANY_CODE, pick_university

if TYPE_CHECKING:
    from .ingest import Ingestor

DOC_SHEET = "Документ вуза"
EXTRACTED_DIR = "extracted"
RE_CODE = re.compile(r"\d{2}\.\d{2}\.\d{2}")
BENEFIT_TYPES = {"bvi": "БВИ", "100": "100 баллов", "extra_points": "ИД (доп. баллы)"}
ROLES = {"winner": "победители", "prizewinner": "призёры", "both": "победители и призёры"}
ROMAN = {1: "I", 2: "II", 3: "III"}
SUBJECT_TEXT = {
    "rus": "русский язык",
    "math": "математика",
    "inf": "информатика",
    "phys": "физика",
    "chem": "химия",
    "bio": "биология",
    "soc": "обществознание",
    "hist": "история",
    "lit": "литература",
    "foreign": "иностранный язык",
    "geo": "география",
}


@dataclass(frozen=True)
class DocRecord:
    record: Record
    title: str  # название документа


def load_documents(conn: psycopg.Connection[Any], directory: Path) -> list[DocRecord]:
    """Записи всех документов; принятые в document_records заменяют файл с тем же url."""
    by_url: dict[str, list[DocRecord]] = {}
    if directory.is_dir():
        try:
            files = load_dir(directory)
        except ExtractionError as exc:
            raise SystemExit(f"Файлы извлечения не прошли проверку:\n{exc}") from None
        for file in files.values():
            by_url[file.document.url] = [DocRecord(r, file.document.title) for r in file.records]
    accepted: dict[str, list[DocRecord]] = defaultdict(list)
    for url, title, record in conn.execute(
        "SELECT document_url, document_title, record FROM document_records ORDER BY id"
    ):
        accepted[url].append(DocRecord(Record.model_validate(record), title))
    by_url.update(accepted)
    return [rec for recs in by_url.values() for rec in recs]


def direction_names(conn: psycopg.Connection[Any]) -> dict[str, str]:
    """Название направления по коду — из направлений других вузов («01.03.02 Прикладная …»)."""
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for code, name in conn.execute(
        "SELECT code, faculty_or_direction FROM programs WHERE code ~ '^\\d\\d\\.\\d\\d\\.\\d\\d$'"
    ):
        rest = clean_text(name)
        if not rest.startswith(code) or len(RE_CODE.findall(rest)) != 1:
            continue
        rest = rest[len(code) :].strip(" -–—:.,")
        if rest:
            counts[code][rest] += 1
    return {code: names.most_common(1)[0][0] for code, names in counts.items()}


def _detail(ing: Ingestor, rec: DocRecord, olympiad_id: int) -> Any:
    from .ingest import DetailRow

    r = rec.record
    ege = r.ege
    return DetailRow(
        university=r.university,
        program_name="",
        benefit_type=BENEFIT_TYPES[r.benefit_type],
        conditions=r.olympiad,
        olympiad_name=r.olympiad,
        olympiad_id=olympiad_id,
        olympiad_profile=r.profile,
        level=", ".join(ROMAN[n] for n in r.levels),
        winner_role=ROLES.get(r.winner_role or "", ""),
        grade=(", ".join(str(n) for n in r.grades) + " класс") if r.grades else "",
        confirm_subject=", ".join(SUBJECT_TEXT[s] for s in ege.subjects) if ege else "",
        min_ege=str(ege.min) if ege and ege.min is not None else "",
        note=" · ".join(x for x in (clean_text(r.division), clean_text(r.note)) if x),
        source_url=r.source.url,
        source_title=rec.title,
        source_page=r.source.page,
        source_quote=r.source.quote,
    )


def apply_documents(
    ing: Ingestor, directory: Path, log: Callable[[str], None]
) -> dict[str, Counter[str]]:
    """Накладывает слой document на собранные XLSX-слои. Возвращает счётчики по вузам."""
    conn = ing.conn
    # профили, склеенные и удалённые прежними шагами, из кэша выбываем
    ing.profile_ids.clear()
    records = load_documents(conn, directory)
    names = direction_names(conn)
    by_university: dict[int, list[DocRecord]] = defaultdict(list)
    uni_names: dict[int, str] = {}
    for rec in records:
        found = pick_university(conn, rec.record.university)
        if found is None:
            log(f"      ! {rec.record.university}: вуза нет в базе, запись пропущена")
            continue
        by_university[found[0]].append(rec)
        uni_names[found[0]] = found[1]
    result: dict[str, Counter[str]] = {}
    for uid, recs in by_university.items():
        uni_name = uni_names[uid]
        stats = result.setdefault(uni_name, Counter())
        _apply_university(ing, uid, recs, names, stats, log)
        log(
            f"      документы, {uni_name}: записей {stats['records']}, добавлено {stats['added']},"
            f" заменено строк XLSX {stats['replaced']}, направлений создано {stats['programs']},"
            f" олимпиад не сопоставлено {stats['unmatched']} (записей {stats['unmatched_records']}),"
            f" повторов {stats['duplicates']}"
        )
        ing.sheet_log.append(
            (
                f"Документ: {uni_name}",
                stats["records"],
                stats["records"] - stats["unmatched_records"],
                stats["added"],
                f"заменено строк XLSX: {stats['replaced']}",
            )
        )
    return result


def _apply_university(
    ing: Ingestor,
    uid: int,
    recs: list[DocRecord],
    names: dict[str, str],
    stats: Counter[str],
    log: Callable[[str], None],
) -> None:
    conn = ing.conn
    stats["records"] += len(recs)

    def programs() -> dict[int, set[str]]:
        return {
            pid: set(RE_CODE.findall(f"{code} {name}"))
            for pid, code, name in conn.execute(
                "SELECT id, code, faculty_or_direction FROM programs WHERE university_id = %s"
                " ORDER BY id",
                (uid,),
            )
        }

    # олимпиады — через справочник; несопоставленные в базу не попадают
    matched: list[tuple[DocRecord, int]] = []
    unmatched: Counter[str] = Counter()
    for rec in recs:
        olympiad_id = ing.olympiad_id_for(rec.record.olympiad)
        if olympiad_id is None:
            unmatched[rec.record.olympiad] += 1
        else:
            matched.append((rec, olympiad_id))

    # направления, которых у вуза нет: код и название из записи или справочника направлений
    known = {c for codes in programs().values() for c in codes}
    for code in sorted({r.record.program_code for r, _ in matched} - {ANY_CODE} - known):
        same = [r for r, _ in matched if r.record.program_code == code]
        name = next(
            (r.record.program_name for r in same if r.record.program_name), names.get(code, "")
        )
        url = same[0].record.source.url
        ing.programs.get_or_create(
            uid,
            f"{code} {name}".strip(),
            code=code,
            source_url=f"{same[0].title} — {url}" if same[0].title else url,
            source_sheet=DOC_SHEET,
            match_by_code=False,
        )
        stats["programs"] += 1
    by_code: dict[str, list[int]] = defaultdict(list)
    coded = []
    for pid, codes in programs().items():
        for code in codes:
            by_code[code].append(pid)
        if codes:
            coded.append(pid)

    # строки документа по ключу (направление, олимпиада, профиль, тип); конкретный код
    # сильнее «*»
    chosen: dict[tuple[int, int, str, str], DocRecord] = {}
    for star in (False, True):
        for rec, olympiad_id in matched:
            r = rec.record
            if (r.program_code == ANY_CODE) != star:
                continue
            for pid in coded if star else by_code.get(r.program_code, []):
                key = (pid, olympiad_id, profile_key(r.profile), BENEFIT_TYPES[r.benefit_type])
                if key in chosen:
                    stats["duplicates"] += 1
                else:
                    chosen[key] = rec
    stats["unmatched"] = len(unmatched)
    stats["unmatched_records"] = sum(unmatched.values())
    for name, count in unmatched.most_common(5):
        log(
            f"      ! олимпиада документа не сопоставлена со справочником: {name} (записей {count})"
        )

    stats["replaced"] += _drop_xlsx_twins(ing, uid, set(chosen))

    with conn.pipeline():
        for (pid, olympiad_id, _, _), rec in chosen.items():
            ing.insert_benefit(
                _detail(ing, rec, olympiad_id),
                program_id=pid,
                layer="document",
                source_sheet=DOC_SHEET,
            )
            stats["added"] += 1


def _drop_xlsx_twins(ing: Ingestor, uid: int, keys: set[tuple[int, int, str, str]]) -> int:
    """Убирает строки XLSX с ключом из keys; строка с несколькими олимпиадами теряет только
    совпавшие связи. Возвращает число затронутых строк льгот."""
    conn = ing.conn
    links: dict[int, list[tuple[int, bool]]] = defaultdict(list)  # льгота -> (связь, совпала)
    for bid, pid, btype, link_id, olympiad_id, profile in conn.execute(
        """SELECT b.id, b.program_id, b.benefit_type, bo.id, bo.olympiad_id,
                  COALESCE(NULLIF(bo.profile, ''), b.olympiad_profile)
           FROM benefits b
           JOIN programs p ON p.id = b.program_id
           JOIN benefit_olympiads bo ON bo.benefit_id = b.id
           WHERE p.university_id = %s AND b.layer IN ('detailed', 'derived')""",
        (uid,),
    ):
        links[bid].append((link_id, (pid, olympiad_id, profile_key(profile), btype) in keys))
    touched = {bid: ls for bid, ls in links.items() if any(m for _, m in ls)}
    whole = [bid for bid, ls in touched.items() if all(m for _, m in ls)]
    parts = [link_id for bid, ls in touched.items() if bid not in whole for link_id, m in ls if m]
    conn.execute("DELETE FROM benefits WHERE id = ANY(%s)", (whole,))
    conn.execute("DELETE FROM benefit_olympiads WHERE id = ANY(%s)", (parts,))
    return len(touched)
