"""Строки таблиц документа -> записи о льготах в едином формате (olymp_domain.extraction)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import unquote

from olymp_domain.extraction import Document, Ege, ExtractionFile, Record, Source, record_key

from . import cells as C
from .columns import classify, looks_like_header, normalize_header
from .context import Context, infer, infer_campaign
from .layout import Line, Loaded, Page

# «Право на прием БВИ» / «Зачисление без вступительных испытаний» / «Право на 100 баллов»
RE_BENEFIT_BVI = re.compile(r"\bБВИ\b|без\s+вступительн|поступлени\w+\s+без", re.IGNORECASE)
RE_BENEFIT_100 = re.compile(r"100\s+баллов|максимальн\w+\s+(?:количество\s+)?баллов", re.IGNORECASE)
# заголовок таблицы по учебным годам: «Соответствие профилей … на 2025/2026 учебный год»
RE_PERIOD = re.compile(
    r"соответстви\w+\s+профил[^\n]{0,200}?\bна\s+(20\d\d)\s*[/-]\s*(?:20)?\d\d\s+учебн",
    re.IGNORECASE,
)
ALL_RUSSIAN = "Всероссийская олимпиада школьников"
RE_NUMBERED = re.compile(r"^(?:№|n\b|п/п)", re.IGNORECASE)


def parse_benefit(text: str) -> str | None:
    bvi, hundred = bool(RE_BENEFIT_BVI.search(text)), bool(RE_BENEFIT_100.search(text))
    if bvi and not hundred:
        return "bvi"
    if hundred and not bvi:
        return "100"
    return None


@dataclass
class Part:
    page: int
    line: Line
    cells: list[str] = field(default_factory=list)  # ячейки части строки, при переносе — свои


@dataclass
class DataRow:
    """Логическая строка таблицы; у строки, перенесённой на другую страницу, несколько частей."""

    roles: list[str]
    header: tuple[str, ...]
    parts: list[Part]
    cells: list[str]
    section: str = ""
    section_code: str = ""
    numbered: bool = False
    ctx: Context = field(default_factory=Context)
    inherited: bool = False  # направление взято у предыдущей строки (ячейка пуста)

    def get(self, role: str) -> str:
        return C.tidy(" ".join(c for r, c in zip(self.roles, self.cells, strict=True) if r == role))

    def has(self, role: str) -> bool:
        return role in self.roles

    def header_text(self, role: str) -> str:
        return " ".join(
            normalize_header(h) for r, h in zip(self.roles, self.header, strict=True) if r == role
        )


@dataclass
class Adapter:
    """Особенности вида таблицы или документа; всё необязательное."""

    name: str = ""
    olympiad_lists: bool = False  # в ячейке олимпиад несколько названий через запятую
    olympiad: Callable[[str], str] | None = None  # название олимпиады из текста шапки
    benefit: str | None = None  # тип льготы, если документ его не называет
    benefit_note: str = ""  # оговорка в записях, у которых тип взят из адаптера
    roles: dict[str, str] = field(default_factory=dict)  # переименование ролей колонок
    programs: Callable[[str], list[C.Program]] | None = None  # направления без кодов (по названию)
    page_filter: Callable[[Page], bool] | None = None
    latest_period_only: bool = False  # таблицы по учебным годам: берём только самый свежий год
    rows: Callable[[list[DataRow]], list[DataRow]] | None = None  # правка строк до сборки записей


@dataclass
class Result:
    file: ExtractionFile
    warnings: list[str] = field(default_factory=list)


def overlay(base: Context, new: Context) -> Context:
    """Условия страницы поверх условий предыдущих: названное на странице заменяет прежнее."""
    return Context(
        benefit=new.benefit or base.benefit,
        role=new.role or base.role,
        ege_min=new.ege_min or base.ege_min,
        grades=new.grades or base.grades,
        olympiad=new.olympiad or base.olympiad,
        star=new.star or base.star,
    )


def _widest_sheets(loaded: Loaded) -> set[int] | None:
    """У xlsx берём листы с самой широкой таблицей: остальные — представления одних и тех же строк."""
    if loaded.kind != "xlsx":
        return None
    widths = {}
    for page in loaded.pages:
        head = next((line for line in page.lines if looks_like_header(line.cells)), None)
        if head is not None:
            widths[page.number] = len([c for c in head.cells if c])
    top = max(widths.values(), default=0)
    return {number for number, width in widths.items() if width == top}


def _classify(header: tuple[str, ...], adapter: Adapter) -> list[str]:
    roles = [adapter.roles.get(role, role) for role in classify(header)]
    # разреженная шапка (ячейки сдвинуты и продублированы) — колонки данных не сопоставить
    if sum(bool(c.strip()) for c in header) < 0.8 * len(header):
        return ["skip"] * len(header)
    return roles


def collect_rows(loaded: Loaded, adapter: Adapter) -> list[DataRow]:
    rows: list[DataRow] = []
    ctx = infer(unquote(loaded.url))
    periods = [int(m.group(1)) for p in loaded.pages for m in RE_PERIOD.finditer(p.plain)]
    latest = max(periods, default=0)
    period = latest
    header: tuple[str, ...] = ()
    roles: list[str] = []
    section, section_code = "", ""
    widest = _widest_sheets(loaded)
    for page in loaded.pages:
        if adapter.page_filter and not adapter.page_filter(page):
            continue
        if widest is not None and page.number not in widest:
            continue
        if adapter.latest_period_only:
            found = [int(m.group(1)) for m in RE_PERIOD.finditer(page.plain)]
            period = max(found, default=period)
            if period < latest:
                continue
        page_ctx = infer(page.plain)
        if adapter.olympiad and (name := adapter.olympiad(page.plain)):
            page_ctx.olympiad = name
        ctx = overlay(ctx, page_ctx)
        for line in page.lines:
            if line.kind == "columns":
                if line.cells:
                    header, roles = line.cells, _classify(line.cells, adapter)
                continue
            if line.kind == "section":
                section, section_code = line.cells[0] if line.cells else line.text, line.code
                continue
            if looks_like_header(line.cells):
                header, roles = line.cells, _classify(line.cells, adapter)
                continue
            width = len(line.cells)
            if not roles or width < 2 or width > len(roles):
                continue
            row_roles = roles[-width:]
            row_header = header[-width:]
            rows.append(
                DataRow(
                    row_roles,
                    row_header,
                    [Part(page.number, line, [C.tidy(c) for c in line.cells])],
                    [C.tidy(c) for c in line.cells],
                    section,
                    section_code or line.code,
                    bool(row_header) and bool(RE_NUMBERED.match(row_header[0].lower())),
                    ctx,
                )
            )
    return rows


def merge_continuations(rows: list[DataRow]) -> list[DataRow]:
    """Строка с пустым номером в нумерованной таблице — продолжение предыдущей (перенос страницы)."""
    stats: dict[tuple[str, ...], list[int]] = {}
    for row in rows:
        if row.numbered:
            counts = stats.setdefault(row.header, [0, 0])
            counts[0] += 1
            counts[1] += bool(row.cells[0])
    merged: list[DataRow] = []
    for row in rows:
        seen = stats.get(row.header)
        numbered = seen is not None and seen[1] / seen[0] >= 0.6
        if numbered and not row.cells[0] and merged and merged[-1].header == row.header:
            prev = merged[-1]
            prev.cells = [C.tidy(f"{a} {b}") for a, b in zip(prev.cells, row.cells, strict=True)]
            prev.parts.extend(row.parts)
        else:
            merged.append(row)
    return merged


def inherit_programs(rows: list[DataRow]) -> list[DataRow]:
    """Пустая ячейка направления — продолжение предыдущей строки той же таблицы (ИТМО, перенос страницы)."""
    last: DataRow | None = None
    for row in rows:
        if not row.has("program"):
            continue
        if row.get("program"):
            last = row
        elif (
            last is not None
            and last.header == row.header
            and not row.section_code
            and not row.numbered
        ):
            for i, role in enumerate(row.roles):
                if role == "program":
                    row.cells[i] = last.cells[i]
                    row.parts[0].cells[i] = last.cells[i]
            row.inherited = True
    return rows


def _quote(row: DataRow, part: Part | None = None) -> str:
    return (part or row.parts[0]).line.text


def _ege(subjects: list[str], minimum: int | None) -> Ege | None:
    if not subjects and minimum is None:
        return None
    return Ege(subjects=subjects, min=minimum)


def records_of(
    row: DataRow,
    adapter: Adapter,
    doc: Document,
    warnings: list[str],
) -> list[Record]:
    ctx = row.ctx
    olympiad_text = row.get("olympiad")
    if row.has("olympiad") and not olympiad_text:
        return []  # ячейка названия пуста (оборвана сетка таблицы): угадывать нечего
    if not olympiad_text and not ctx.olympiad:
        return []
    olympiads = (
        C.split_olympiads(olympiad_text)
        if adapter.olympiad_lists and olympiad_text
        else [C.unbreak(olympiad_text) or ctx.olympiad]
    )
    star_note = ""
    if "*" in olympiads:
        if not ctx.star:
            olympiads = [name for name in olympiads if name != "*"]
        else:
            olympiads = [ctx.star if name == "*" else name for name in olympiads]
            star_note = "«*» в документе: " + ctx.star[0].lower() + ctx.star[1:]
    if not olympiads:
        return []
    profiles = C.split_profiles(row.get("profile")) or [""]
    if not row.has("profile") and not olympiad_text:
        return []

    benefit = parse_benefit(row.get("benefit")) if row.has("benefit") else None
    own_benefit = benefit or ctx.benefit
    benefit = own_benefit or adapter.benefit
    if benefit is None:
        return []
    role = C.parse_role(row.get("role")) if row.has("role") else None
    role = role or ctx.role
    levels = C.parse_levels(row.get("level"))
    grades: list[int] = C.parse_grades(row.get("grades")) if row.has("grades") else list(ctx.grades)
    if not olympiad_text and ctx.olympiad == ALL_RUSSIAN:
        grades = []  # диплом ВсОШ не привязан к классу, а «10 или 11» в шапке — про другие олимпиады
    subjects = C.parse_subjects(row.get("ege_subject"))
    minimum = C.parse_min(row.get("ege_min")) if row.has("ege_min") else None
    if minimum is None and row.has("ege_subject"):
        minimum = C.parse_min(row.header_text("ege_subject"))
    if minimum is None and not (row.has("ege_subject") and not subjects):
        minimum = (
            ctx.ege_min
        )  # порог из шапки относится к предмету; «—» в колонке предметов — ЕГЭ не нужен
    notes = [star_note] if star_note else []
    if own_benefit is None and adapter.benefit_note:
        notes.append(adapter.benefit_note)
    if row.has("note"):
        notes.append(f"ОП {row.get('note')}")

    # направления: коды в ячейке, иначе из заголовка раздела, иначе по названию, иначе «*»
    programs: list[tuple[C.Program, Part]] = []
    excluded: list[str] = []
    if row.has("program"):
        for part in row.parts:
            texts = [
                c
                for r, c in zip(row.roles[-len(part.cells) :], part.cells, strict=False)
                if r == "program"
            ]
            found, everything = C.parse_programs(" ".join(texts))
            if everything:
                excluded.extend(p.code for p in found)
            else:
                programs.extend((p, row.parts[0]) for p in found)
    if not programs and not excluded:
        if adapter.programs is not None and row.get("program"):
            programs = [(p, row.parts[0]) for p in adapter.programs(row.get("program"))]
        elif row.section_code:
            name = C.tidy(re.sub(r"^.*?\d{2}\.\d{2}\.\d{2}", "", row.section))
            programs = [(C.Program(row.section_code, name), row.parts[0])]
        elif not row.has("program"):
            programs = [(C.Program("*"), row.parts[0])]
    if excluded and not programs:
        note = "все направления, кроме " + ", ".join(excluded)
        programs = [(C.Program("*", "", note), row.parts[0])]
    if not programs:
        return []

    division = row.section if row.section and not row.section_code else ""
    records = []
    for olympiad in olympiads:
        for profile in profiles:
            for program, part in programs:
                records.append(
                    Record(
                        university=doc.university,
                        campaign=doc.campaign,
                        program_code=program.code,
                        program_name=program.name,
                        division=division.title() if division.isupper() else division,
                        benefit_type=benefit,
                        olympiad=olympiad,
                        profile=profile,
                        levels=levels,
                        winner_role=role,
                        grades=grades,
                        ege=_ege(subjects, minimum),
                        source=Source(
                            url=doc.url,
                            sha256=doc.sha256,
                            page=part.page,
                            row=part.line.row,
                            quote=_quote(row, part),
                        ),
                        note="; ".join(
                            n
                            for n in [
                                program.note,
                                "направление не указано на странице, таблица продолжает "
                                "направление предыдущей"
                                if row.inherited
                                else "",
                                *notes,
                            ]
                            if n
                        ),
                    )
                )
    return records


def merge_duplicates(records: list[Record], groups: list[str]) -> list[Record]:
    """Одинаковый ключ и классы — одна запись: предметы ЕГЭ и оговорки объединяются."""
    merged: dict[tuple[object, ...], Record] = {}
    for rec, group in zip(records, groups, strict=True):
        key = (record_key(rec), tuple(rec.grades), rec.source.page, group)
        old = merged.get(key)
        if old is None:
            merged[key] = rec
            continue
        if rec.ege and old.ege:
            old.ege.subjects = list(dict.fromkeys([*old.ege.subjects, *rec.ege.subjects]))
        elif rec.ege:
            old.ege = rec.ege
        old.levels = sorted(set(old.levels) | set(rec.levels))
        if rec.note and rec.note not in old.note:
            old.note = " | ".join(n for n in (old.note, rec.note) if n)
    return list(merged.values())


def extract(
    loaded: Loaded,
    *,
    university: str,
    campaign: int | None = None,
    title: str = "",
    adapter: Adapter | None = None,
) -> Result:
    adapter = adapter or Adapter()
    year = campaign or infer_campaign("\n".join(p.plain for p in loaded.pages[:3]) + loaded.url)
    doc = Document(
        university=university,
        campaign=year,
        url=loaded.url,
        sha256=loaded.sha256,
        title=title,
        pages=[1],
    )
    warnings: list[str] = []
    rows = inherit_programs(merge_continuations(collect_rows(loaded, adapter)))
    if adapter.rows:
        rows = adapter.rows(rows)
    records: list[Record] = []
    groups: list[str] = []  # «Образовательная программа»: записи разных ОП не склеиваем
    for row in rows:
        made = records_of(row, adapter, doc, warnings)
        records.extend(made)
        groups.extend([row.get("note")] * len(made))
    records = merge_duplicates(records, groups)
    doc.pages = sorted({r.source.page for r in records}) or [1]
    return Result(ExtractionFile(document=doc, records=records), warnings)
