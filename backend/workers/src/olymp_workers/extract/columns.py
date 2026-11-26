"""Роли колонок таблицы по заголовку: что в какой колонке лежит."""

from __future__ import annotations

import re
from collections.abc import Sequence

HEADER_WORDS = re.compile(
    r"^№|п/п|олимпиад|наименован|названи|профил|предмет|направлен|специальност|уровень|класс|"
    r"победител|диплом|льгот|право|егэ|баллов|подготовк|программ",
    re.IGNORECASE,
)
RE_BROKEN = re.compile(r"(?<=[А-Яа-яЁё])-\s+(?=[а-яё])")

# порядок важен: первое совпадение определяет роль
RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (role, re.compile(pattern, re.IGNORECASE))
    for role, pattern in (
        ("skip", r"^(?:№|n\b|п/п|номер)"),
        ("skip", r"уровень\s+образовани"),
        ("skip", r"предмет\w*\s+(?:или|и)\s+специальност"),
        ("ege_min", r"колич\w+\s+баллов|минимальн\w+\s+балл|порог"),
        ("benefit", r"вид\s+особого\s+права|предоставляем\w+\s+(?:льгот|особ)|вид\s+льготы"),
        ("role", r"^кому|победител\w*\s*/?\s*(?:или\s+)?призер|^диплом"),
        ("grades", r"класс"),
        ("level", r"уровень"),
        ("skip", r"предмет\w*\s+зачет"),
        ("ege_subject", r"профилирующ|подтвержд|егэ|^предмет\W*(?:\W|\s)*балл"),
        (
            "program",
            r"^(?:код\s+и\s+)?(?:наименован\w+\s+)?(?:профильн\w+\s+)?(?:направлен|специальност)",
        ),
        ("note", r"^образовательн\w+\s+программ"),
        ("profile", r"\bпрофил[ьи]\b"),
        ("profile_alt", r"^предмет\b.*олимпиад|предмет.*проводится"),
        ("skip", r"^предмет\w*\s+олимпиад"),
        ("ege_subject", r"^общеобразовательн\w+\s+предмет"),
        ("olympiad", r"олимпиад"),
        ("program", r"направлен|специальност|программ|код"),
    )
)


def normalize_header(cell: str) -> str:
    """Заголовок для сопоставления: без переносов в словах, а перевёрнутый текст (ИТМО) — прямой."""
    text = RE_BROKEN.sub("", " ".join(cell.split())).lower()
    if not text:
        return ""
    if not HEADER_WORDS.search(text) and HEADER_WORDS.search(text[::-1]):
        return text[::-1]
    return text


def classify(header: Sequence[str]) -> list[str]:
    roles = []
    for cell in header:
        text = normalize_header(cell)
        role = "skip"
        if text:
            role = next((r for r, pattern in RULES if pattern.search(text)), "skip")
        roles.append(role)
    # профиль только один: «Предмет олимпиады» не нужен, если есть «Профиль олимпиады»
    if "profile" in roles:
        roles = ["skip" if r == "profile_alt" else r for r in roles]
    else:
        roles = ["profile" if r == "profile_alt" else r for r in roles]
    return roles


def looks_like_header(cells: Sequence[str]) -> bool:
    """Строка похожа на заголовок: не меньше двух ячеек со словами заголовка и нет кодов направлений."""
    filled = [c for c in cells if c.strip()]
    if len(filled) < 2:
        return False
    hits = sum(bool(HEADER_WORDS.search(normalize_header(c))) for c in filled)
    has_code = any(re.search(r"\d{2}\.\d{2}\.\d{2}", c) for c in filled)
    return hits >= 2 and hits * 5 >= len(filled) * 4 and not has_code
