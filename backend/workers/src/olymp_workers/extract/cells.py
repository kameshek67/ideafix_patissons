"""Разбор ячеек таблиц вузов: направления, профили, «кому», классы, уровни, предметы ЕГЭ."""

from __future__ import annotations

import re
from dataclasses import dataclass

from olymp_domain.ege import SUBJECTS
from olymp_domain.textutils import squash

RE_CODE = re.compile(r"(?<![\d.])(\d{2}\.\d{2}\.\d{2})(?![\d])")
RE_WS = re.compile(r"\s+")
# перенос слова через дефис и пробел: «бизнес- процессов», «Санкт- Петербургского»
RE_BROKEN = re.compile(r"(?<=[А-Яа-яЁёA-Za-z])-\s+(?=[а-яё])")
RE_EXCEPT = re.compile(r"все\W+(?:за\s+)?исключен\w+|все\W+кроме", re.IGNORECASE)


def tidy(text: str) -> str:
    """Пробелы в одну строку; склеенные переносом части слов не трогаем (цитата останется дословной)."""
    return RE_WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def unbreak(text: str) -> str:
    """Для названий: «бизнес- процессов» -> «бизнес-процессов»."""
    return RE_BROKEN.sub("-", tidy(text))


# ---------------------------------------------------------------- направления


@dataclass(frozen=True)
class Program:
    code: str
    name: str = ""
    note: str = ""


def _program_name(rest: str) -> tuple[str, str]:
    """Название направления и оговорка в скобках: «Лингвистика (ОП «…»)» -> («Лингвистика», «ОП «…»»)."""
    rest = tidy(rest).strip(" ,;")
    cut = rest.find(" (")
    if cut == -1:
        return rest, ""
    return rest[:cut].strip(), rest[cut + 1 :].strip()


def parse_programs(text: str) -> tuple[list[Program], bool]:
    """Направления из ячейки и признак «все, за исключением …» (тогда коды — исключения).

    «38.03.01 38.03.02» и «06.03.01 Биология 05.03.06 Экология» — оба варианта разбираются."""
    text = tidy(text)
    everything = bool(RE_EXCEPT.search(text))
    parts = RE_CODE.split(text)
    programs = []
    for i in range(1, len(parts), 2):
        name, note = _program_name(parts[i + 1])
        programs.append(Program(parts[i], name, note))
    return programs, everything


# ---------------------------------------------------------------- списки


def split_top(text: str, seps: str = ";") -> list[str]:
    """Делит по разделителям вне скобок и кавычек."""
    out: list[str] = []
    depth = 0
    quoted = False
    cur: list[str] = []
    for ch in text:
        if ch == "«":
            depth += 1
        elif ch == "»":
            depth = max(0, depth - 1)
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == '"':
            quoted = not quoted
        if ch in seps and depth == 0 and not quoted:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [tidy(p) for p in out if tidy(p)]


# школьные предметы: «робототехника, технология» в списке профилей — два профиля
SCHOOL_SUBJECTS = {
    squash(s)
    for s in [
        "астрономия",
        "биология",
        "география",
        "информатика",
        "история",
        "литература",
        "математика",
        "обществознание",
        "право",
        "робототехника",
        "технология",
        "физика",
        "химия",
        "экология",
        "экономика",
        "иностранные",
        "языки",
        "иностранный",
        "язык",
        "русский",
        "язык",
        "искусство",
        "основы",
        "безопасности",
        "и",
        "защиты",
        "Родины",
        "физическая",
        "культура",
    ]
}


def split_profiles(text: str) -> list[str]:
    """Профили из ячейки: через «;», а запятая делит, только если все части — названия предметов."""
    profiles: list[str] = []
    for part in split_top(unbreak(text), ";"):
        pieces = split_top(part, ",")
        if len(pieces) > 1 and all(squash(p) in SCHOOL_SUBJECTS for p in pieces):
            profiles.extend(pieces)
        else:
            profiles.append(part)
    return profiles


def split_olympiads(text: str) -> list[str]:
    """Названия олимпиад через запятую вне кавычек; следующее название начинается с заглавной."""
    pieces = split_top(unbreak(text), ",")
    out: list[str] = []
    for piece in pieces:
        if out and piece[:1].islower():
            out[-1] += ", " + piece
        else:
            out.append(piece)
    return out


# ---------------------------------------------------------------- «кому», классы, уровни


def parse_role(text: str) -> str | None:
    """winner / prizewinner / both по словам «победитель», «призёр»; нет слов — None."""
    low = text.lower().replace("ё", "е")
    winner = bool(re.search(r"победител|\bпоб\b", low))
    prize = bool(re.search(r"призер|\bприз\b", low))
    if winner and prize:
        return "both"
    if winner:
        return "winner"
    if prize:
        return "prizewinner"
    return None


ROMAN = {"I": 1, "II": 2, "III": 3}


def parse_levels(text: str) -> list[int]:
    """«1 или 2», «I, II», «III», «1-2» -> [1, 2]."""
    found: set[int] = set()
    for a, b in re.findall(r"\b([123])\s*[-–—]\s*([123])\b", text):
        found.update(range(int(a), int(b) + 1))
    found.update(int(n) for n in re.findall(r"(?<![\d.])[123](?![\d.])", text))
    found.update(ROMAN[r] for r in re.findall(r"\b(?:III|II|I)\b", text))
    return sorted(found)


def parse_grades(text: str) -> list[int]:
    """«11 класс», «10 или 11», «9-11» -> классы."""
    found: set[int] = set()
    for a, b in re.findall(r"\b(9|10|11)\s*[-–—]\s*(9|10|11)\b", text):
        found.update(range(int(a), int(b) + 1))
    found.update(int(n) for n in re.findall(r"(?<![\d.])(9|10|11)(?![\d.])", text))
    return sorted(found)


# ---------------------------------------------------------------- предметы и баллы ЕГЭ

_FORMS = sorted(
    ((form, code) for code, forms in SUBJECTS.items() for form in forms),
    key=lambda pair: -len(pair[0]),
)
_LANGUAGES = ("английск", "немецк", "французск", "испанск", "китайск", "итальянск")


def subject_code(token: str) -> str | None:
    key = squash(token)
    if not key:
        return None
    if key.endswith("язык") and key != "русскийязык" and key.startswith(_LANGUAGES):
        return "foreign"
    for form, code in _FORMS:
        if key == form or (key.startswith(form) and len(key) - len(form) <= 12):
            return code
    return None


def parse_subjects(text: str) -> list[str]:
    """Коды предметов ЕГЭ из списка «математика; физика, информатика / химия»; незнакомое пропускается."""
    codes: list[str] = []
    for part in re.split(r"[;,/]|\bили\b|\bи\b(?! икт)", unbreak(text), flags=re.IGNORECASE):
        code = subject_code(re.sub(r"\(.*?\)", "", part))
        if code and code not in codes:
            codes.append(code)
    return codes


RE_MIN = re.compile(
    r"(?:не\s+(?:ниже|менее)|от|≥)\s*(\d{2,3})\s*(?:балл\w*)?|(\d{2,3})\s*(?:\+|и\s+более|балл\w*\s+и\s+более)",
    re.IGNORECASE,
)


def parse_min(text: str) -> int | None:
    """Порог ЕГЭ из «75 и более», «не ниже 75 баллов»; одно число 40–100 тоже порог."""
    for m in RE_MIN.finditer(text):
        value = int(m.group(1) or m.group(2))
        if 40 <= value <= 100:
            return value
    numbers = [int(n) for n in re.findall(r"(?<![\d.])\d{2,3}(?![\d.])", text)]
    numbers = [n for n in numbers if 40 <= n <= 100]
    return numbers[0] if len(numbers) == 1 else None
