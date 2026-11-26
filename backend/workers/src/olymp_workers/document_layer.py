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
from olymp_domain.textutils import clean_text, squash

from .eval_extract import ANY_CODE, pick_university

if TYPE_CHECKING:
    from .ingest import Ingestor

DOC_SHEET = "Документ вуза"
EXTRACTED_DIR = "extracted"
RE_CODE = re.compile(r"\d{2}\.\d{2}\.\d{2}")
BENEFIT_TYPES = {"bvi": "БВИ", "100": "100 баллов", "extra_points": "ИД (доп. баллы)"}
ROLES = {"winner": "победители", "prizewinner": "призёры", "both": "победители и призёры"}
# «Все из перечня олимпиад школьников», «Все олимпиады … включённые в Перечень»
RE_UMBRELLA = re.compile(r"^все\b.*перечн|перечен", re.IGNORECASE)
RE_PARENS = re.compile(r"\s*\([^)]*\)")
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
            f" повторов {stats['duplicates']}, по перечню раскрыто {stats['umbrella']}"
            f" (уже были {stats['umbrella_dups']}, профиль не найден {stats['umbrella_empty']})"
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
    umbrella: list[DocRecord] = []
    unmatched: Counter[str] = Counter()
    for rec in recs:
        olympiad_id = ing.olympiad_id_for(rec.record.olympiad)
        if olympiad_id is None and RE_UMBRELLA.search(clean_text(rec.record.olympiad)):
            umbrella.append(rec)
        elif olympiad_id is None:
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
    if umbrella:
        _apply_umbrella(ing, umbrella, by_code, coded, stats, log)


def _apply_umbrella(
    ing: Ingestor,
    recs: list[DocRecord],
    by_code: dict[str, list[int]],
    coded: list[int],
    stats: Counter[str],
    log: Callable[[str], None],
) -> None:
    """Записи «все олимпиады перечня» раскрываются в пары «олимпиада + профиль» РСОШ.

    Профиль записи ищется в справочнике профилей так же, как в правилах «по профилю»; без
    профиля берутся все пары. ВсОШ и международные не входят, уровень пары — из levels записи.
    Строки идут слоем derived; пары, которые у направления уже есть, не повторяются.
    """
    from .ingest import join_parts

    conn = ing.conn
    index, meta = ing.profile_index()
    rsosh = {pid: m for pid, m in meta.items() if ing.olympiad_kinds.get(m[0], "rsosh") == "rsosh"}
    pids = sorted({pid for pids in by_code.values() for pid in pids} | set(coded))
    have_ids: set[tuple[int, int, int, str]] = set()
    have_text: set[tuple[int, int, str, str]] = set()
    for pid, btype, olympiad_id, profile_id, profile in conn.execute(
        """SELECT b.program_id, b.benefit_type, bo.olympiad_id, bo.profile_id,
                  COALESCE(NULLIF(bo.profile, ''), b.olympiad_profile)
           FROM benefits b JOIN benefit_olympiads bo ON bo.benefit_id = b.id
           WHERE b.program_id = ANY(%s) AND b.layer IN ('detailed', 'derived', 'document')""",
        (pids,),
    ):
        have_ids.add((pid, olympiad_id, profile_id or 0, btype))
        have_text.add((pid, olympiad_id, profile_key(profile or ""), btype))
    pairs_of: dict[tuple[str, tuple[int, ...]], list[int]] = {}
    warned: set[tuple[str, tuple[int, ...]]] = set()
    for rec in recs:
        r = rec.record
        btype = BENEFIT_TYPES[r.benefit_type]
        levels = {ROMAN[n] for n in r.levels}
        query = RE_PARENS.sub("", clean_text(r.profile)).strip()
        cache_key = (squash(query), tuple(r.levels))
        if cache_key not in pairs_of:
            ids = index.find(query) if query else list(meta)
            pairs_of[cache_key] = [
                i
                for i in ids
                if i in rsosh and (not levels or not meta[i][2] or meta[i][2] in levels)
            ]
        if not pairs_of[cache_key]:
            stats["umbrella_empty"] += 1
            if cache_key not in warned:
                warned.add(cache_key)
                log(
                    f"      ! «{r.olympiad[:40]}»: профиль «{r.profile}» не найден среди олимпиад перечня"
                )
            continue
        star = r.program_code == ANY_CODE
        for pid in coded if star else by_code.get(r.program_code, []):
            for profile_id in pairs_of[cache_key]:
                olympiad_id, profile_name, profile_level = meta[profile_id]
                if (pid, olympiad_id, profile_id, btype) in have_ids or (
                    pid,
                    olympiad_id,
                    profile_key(profile_name),
                    btype,
                ) in have_text:
                    stats["umbrella_dups"] += 1
                    continue
                have_ids.add((pid, olympiad_id, profile_id, btype))
                name = ing.olympiad_names.get(olympiad_id, "")
                detail = _detail(ing, rec, olympiad_id)
                detail.olympiad_name = name
                detail.olympiad_profile = profile_name
                detail.level = profile_level or detail.level
                detail.conditions = join_parts(
                    name,
                    f"профиль: {profile_name}",
                    f"уровень {detail.level}" if detail.level else "",
                )
                detail.note = " · ".join(
                    x
                    for x in (
                        "Правило документа: любая олимпиада перечня с этим профилем",
                        detail.note,
                    )
                    if x
                )
                ing.insert_benefit(detail, program_id=pid, layer="derived", source_sheet=DOC_SHEET)
                stats["umbrella"] += 1
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
