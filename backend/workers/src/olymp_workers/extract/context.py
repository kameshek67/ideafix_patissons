"""Условия из шапки документа, которые действуют на все строки таблицы, если строка не говорит иного."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cells import tidy

RE_BVI = re.compile(
    r"без\s+вступительн\w+\s+испытани|(?<![А-Яа-яЁёA-Za-z])БВИ(?![А-Яа-яЁёA-Za-z])", re.IGNORECASE
)
RE_100 = re.compile(r"\b100\s+баллов|приравнива\w+\s+к\s+лицам", re.IGNORECASE)
RE_BOTH_ROLES = re.compile(r"победител\w+\s+(?:и|или|и/или)\s+призер\w+", re.IGNORECASE)
RE_ONLY_WINNERS = re.compile(
    r"только\s+победител|победител\w+\s*,?\s+но\s+не\s+призер", re.IGNORECASE
)
RE_MIN = re.compile(
    r"ЕГЭ[^.;]{0,120}?(?:не\s+(?:ниже|менее)|от)\s*(\d{2,3})\s*балл"
    r"|(?:не\s+(?:ниже|менее)|от)\s*(\d{2,3})\s*балл\w*\s+(?:по|ЕГЭ)",
    re.IGNORECASE | re.DOTALL,
)
RE_GRADES = re.compile(
    r"\b(9|10|11)\s*(?:-?м)?\s*(?:и|или|,|-|–)\s*(9|10|11)\s*(?:-?м)?\s*класс|"
    r"\b(9|10|11)\s*(?:-?м)?\s*класс",
    re.IGNORECASE,
)
RE_ALL_RUSSIAN = re.compile(r"всероссийск\w+\s+олимпиад\w+\s+школьников", re.IGNORECASE)
RE_STAR = re.compile(r"^\*\s*(Все\s+олимпиады[^\n]*)", re.MULTILINE)
RE_YEAR = re.compile(r"\b(20[2-3]\d)\b")


@dataclass
class Context:
    benefit: str | None = None  # bvi | 100
    role: str | None = None
    ege_min: int | None = None
    grades: list[int] = field(default_factory=list)
    olympiad: str = ""
    star: str = ""  # сноска «* Все олимпиады …»: что значит «*» в колонке олимпиад


def infer(text: str) -> Context:
    """Условия из текста шапки; неоднозначное остаётся пустым: пустое значение лучше догадки."""
    raw, text = text, tidy(text)
    ctx = Context()
    bvi, hundred = bool(RE_BVI.search(text)), bool(RE_100.search(text))
    if bvi != hundred:
        ctx.benefit = "bvi" if bvi else "100"
    if RE_BOTH_ROLES.search(text) and not RE_ONLY_WINNERS.search(text):
        ctx.role = "both"
    mins = {int(m.group(1) or m.group(2)) for m in RE_MIN.finditer(text)}
    mins = {m for m in mins if 40 <= m <= 100}
    if len(mins) == 1:
        ctx.ege_min = mins.pop()
    for m in RE_GRADES.finditer(text):
        grades = [int(g) for g in m.groups() if g]
        if ctx.grades and sorted(grades) != ctx.grades:
            ctx.grades = []  # разные классы в разных местах — не угадываем
            break
        ctx.grades = sorted(grades)
    if RE_ALL_RUSSIAN.search(text):
        ctx.olympiad = "Всероссийская олимпиада школьников"
    if star := RE_STAR.search(raw):
        ctx.star = star.group(1).strip()
    return ctx


def infer_campaign(text: str, default: int = 2026) -> int:
    """Год приёма: самый частый год в начале документа; при равенстве — меньший (2026/2027 -> 2026)."""
    years = [int(y) for y in RE_YEAR.findall(text)]
    if not years:
        return default
    counts = {y: years.count(y) for y in set(years)}
    best = max(counts.values())
    return min(y for y, n in counts.items() if n == best)
