"""
Текстовые утилиты для разбора условий приёма по олимпиадам.

Исходные таблицы собраны из PDF/HTML приёмных комиссий, поэтому текст «грязный»:
в слова вклеены цифры («Всероссийская о4л импиада»), разорваны переносы,
разные кавычки и тире. Здесь — нормализация, «схлопывание» названий
олимпиад в устойчивый ключ и алгоритмические экстракторы (уровень, роль,
класс, подтверждающий ЕГЭ).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote

# --------------------------------------------------------------------------
# нормализация
# --------------------------------------------------------------------------

RE_WS = re.compile(r"\s+")
RE_EXT_LINK = re.compile(r"\(\s*внешн\w*\s+ссылк\w*\s*\)", re.IGNORECASE)
# цифра, «вклеенная» в слово: о4л импиада, ш8 кольников, «2Ш аг»
RE_GLUED_DIGIT = re.compile(r"(?<=[А-Яа-яЁё])\d+|\d+(?=[А-Яа-яЁё])")
RE_EDGE_DIGIT = re.compile(r"^\s*\d+\s+|\s+\d+\s*$")
RE_QUOTED = re.compile(r"[«\"]([^«»\"]{2,80})[»\"]")
RE_CODE = re.compile(r"\b(\d{2}\.\d{2}\.\d{2})\b")

QUOTES = {
    "«": '"',
    "»": '"',
    "“": '"',
    "”": '"',
    "„": '"',
    "‘": "'",
    "’": "'",
    "‚": "'",
}
DASHES = {"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"}


def clean_text(value) -> str:
    """Базовая чистка ячейки: None -> '', схлопывание пробелов, NBSP."""
    if value is None:
        return ""
    s = str(value)
    s = s.replace("\xa0", " ").replace("​", "").replace("\r", " ")
    s = RE_WS.sub(" ", s).strip()
    return s


def clean_name(value) -> str:
    """Чистка названия олимпиады: убираем «(внешняя ссылка)» и вклеенные цифры."""
    s = clean_text(value)
    if not s:
        return ""
    s = RE_EXT_LINK.sub(" ", s)
    s = RE_GLUED_DIGIT.sub("", s)
    s = RE_EDGE_DIGIT.sub(" ", s)
    s = RE_WS.sub(" ", s).strip(" -–—;,.")
    return s


RE_BROKEN_HYPHEN = re.compile(r"(?<=[А-Яа-яЁёA-Za-z])-\s+(?=[А-Яа-яЁёa-z])")


def clean_profile(value) -> str:
    """
    Профиль олимпиады из таблиц: «автоматизация бизнес- процессов»,
    «Математика», «ИНФОРМАТИКА» -> «автоматизация бизнес-процессов», «математика».
    """
    s = clean_name(value)
    if not s:
        return ""
    s = RE_BROKEN_HYPHEN.sub("-", s)
    s = s.strip(" «»\"'.,;:-")
    if not s:
        return ""
    # один и тот же профиль в исходниках встречается в разном регистре
    if s.isupper():
        return s.lower()
    if s[:1].isupper() and not s[1:2].isupper():
        return s[0].lower() + s[1:]
    return s


def squash(value) -> str:
    """
    Ключ сравнения: только буквы, нижний регистр, ё->е.
    Устойчив к мусорным цифрам, кавычкам, пробелам и переносам.
    """
    s = clean_text(value).lower().replace("ё", "е")
    return "".join(ch for ch in s if ch.isalpha())


def has_glued_digits(value: str) -> bool:
    return bool(RE_GLUED_DIGIT.search(clean_text(value)))


def normalize_punct(value: str) -> str:
    s = clean_text(value)
    for src, dst in QUOTES.items():
        s = s.replace(src, dst)
    for src, dst in DASHES.items():
        s = s.replace(src, dst)
    return s


# часть ссылок в таблице содержит пробел перед расширением: «…/Olimpiady_БВО .pdf»
RE_HTTP_URL = re.compile(r'https?://[^\s;,<>"\')]+(?:\s+\.(?:pdf|docx?|xlsx?|rtf))?', re.IGNORECASE)


def split_source(value) -> tuple[str, str]:
    """
    Поле «Источник» в таблице — это текст, внутри которого может быть ссылка:
    «Приложение 2 «Особые права… 2026» — https://ba.hse.ru/…» ->
    ('Приложение 2 «Особые права… 2026»', 'https://ba.hse.ru/…').

    Ссылка возвращается percent-encoded: часть путей содержит кириллицу и пробелы.
    """
    text = clean_text(value)
    if not text:
        return "", ""
    match = RE_HTTP_URL.search(text)
    if not match:
        return text, ""
    url = match.group(0).rstrip(".,;)")
    title = (text[: match.start()] + " " + text[match.end() :]).strip()
    title = RE_WS.sub(" ", title).strip(" —–-;,:()")
    # пробелы и кириллица в пути ломают ссылку в браузере
    safe = "".join(ch if ord(ch) < 128 and ch != " " else quote(ch, safe="") for ch in url)
    return title, safe


def extract_codes(value) -> list[str]:
    """Коды направлений вида 01.03.02 из произвольного текста."""
    return RE_CODE.findall(clean_text(value))


def short_from_quotes(name: str) -> str | None:
    """«Высшая проба» из «Всероссийская олимпиада школьников «Высшая проба»»."""
    m = RE_QUOTED.findall(clean_text(name))
    if not m:
        return None
    best = max(m, key=len).strip(" -–—")
    if len(best) < 3 or len(best) > 60:
        return None
    return best


# --------------------------------------------------------------------------
# экстракторы ключевых слов
# --------------------------------------------------------------------------

ROMAN = {"i": "I", "ii": "II", "iii": "III", "1": "I", "2": "II", "3": "III"}

# «уровень» пишут во всех падежах (уровень / уровня / ур. / ур), поэтому уров\w*
RE_LEVEL_WORD = re.compile(
    r"(?:уров\w*|\bур\.?)\s*[:№-]?\s*(I{1,3}|[123])\b"
    r"|\b(I{1,3}|[123])\s*(?:-?\s*(?:ой|го|й)?\s*)?(?:уров\w*|\bур\b\.?)",
    re.IGNORECASE,
)
RE_GRADE = re.compile(r"\b(9|10|11)\s*(?:[-–—,]\s*(?:9|10|11)\s*)*кл(?:асс\w*|\.)", re.IGNORECASE)
RE_EGE = re.compile(r"(?:≥|не\s+ниже|от)?\s*(\d{2,3})\s*(?:\+|и\s+более|балл\w*)", re.IGNORECASE)


def norm_level(value) -> str:
    """'1', 'I', 'ур. 2' -> 'I'/'II'/'III'. Пустая строка, если не распознано."""
    s = clean_text(value).lower().replace(" ", "")
    s = s.strip(".:;")
    if s in ROMAN:
        return ROMAN[s]
    m = RE_LEVEL_WORD.search(clean_text(value))
    if m:
        token = (m.group(1) or m.group(2) or "").lower()
        return ROMAN.get(token, "")
    return ""


def find_levels(text: str) -> list[str]:
    out: list[str] = []
    for m in RE_LEVEL_WORD.finditer(clean_text(text)):
        token = (m.group(1) or m.group(2) or "").lower()
        lvl = ROMAN.get(token)
        if lvl and lvl not in out:
            out.append(lvl)
    return out


def find_roles(text: str) -> list[str]:
    s = clean_text(text).lower().replace("ё", "е")
    out = []
    if "только победител" in s:
        out.append("только победители")
    elif "победител" in s:
        out.append("победители")
    if "призер" in s:
        out.append("призёры")
    return out


def norm_role(value) -> str:
    """'поб.+приз.', 'только поб.', 'победитель и призёр' -> единая формулировка."""
    s = clean_text(value).lower().replace("ё", "е")
    if not s:
        return ""
    only = "только" in s
    winner = "победител" in s or re.search(r"\bпоб(ед)?\b|\bпоб(ед)?\.", s) is not None
    prizer = "призер" in s or re.search(r"\bприз\b|\bприз\.", s) is not None
    if winner and prizer:
        return "только победители" if only and "призер" not in s else "победители и призёры"
    if winner:
        return "только победители" if only else "победители"
    if prizer:
        return "призёры"
    return clean_text(value)


def find_grades(text: str) -> list[str]:
    out = []
    for m in RE_GRADE.finditer(clean_text(text)):
        g = m.group(1)
        if g not in out:
            out.append(g)
    return out


def find_ege_thresholds(text: str) -> list[str]:
    out = []
    for m in RE_EGE.finditer(clean_text(text)):
        v = m.group(1)
        if 40 <= int(v) <= 100 and v not in out:
            out.append(v)
    return out


SUBJECTS = [
    "математика",
    "информатика",
    "физика",
    "химия",
    "биология",
    "география",
    "история",
    "обществознание",
    "литература",
    "русский язык",
    "английский язык",
    "иностранный язык",
    "астрономия",
    "экономика",
    "право",
    "экология",
    "лингвистика",
    "журналистика",
    "искусство",
    "черчение",
    "рисунок",
    "технология",
    "труд",
]


def find_subjects(text: str) -> list[str]:
    s = clean_text(text).lower().replace("ё", "е")
    return [subj for subj in SUBJECTS if subj.replace("ё", "е") in s]


# --------------------------------------------------------------------------
# разбор перечислений из листа «База»
# --------------------------------------------------------------------------

RE_BRACKET_PREFIX = re.compile(r"^\s*\[[^\]]{0,80}\]\s*")
RE_ROLE_PREFIX = re.compile(
    r"^\s*(победител\w*(\s+и\s+призёр\w*)?|призёр\w*|только\s+победител\w*)\s*\[?\d*\]?\s*:\s*",
    re.IGNORECASE,
)
RE_LEVEL_TAIL = re.compile(r":\s*([123])\s*$")
RE_YEARS = re.compile(r"\b(20\d\d(?:\s*/\s*\d{2,4})?)\b")


@dataclass
class ParsedCondition:
    """Одна строка перечисления: «олимпиада (профиль, уровень)»."""

    name: str
    profile: str = ""
    level: str = ""
    role: str = ""
    grade: str = ""
    raw: str = ""
    # название стоит в списке точных названий (ИТМО): можно сопоставлять и короткие сокращения
    exact: bool = False


# Как олимпиады названы в списках ИТМО «Предмет: олимпиады — условие» -> строка для поиска в справочнике
SUBJECT_LIST_ALIASES: dict[str, str] = {
    "московская": "МОШ",
    "санктпетербургская": "Санкт-Петербургская олимпиада школьников",
    "нтобольшиеданные": "НТО",
}


def split_top_level(text: str, separators: str = ";") -> list[str]:
    """Режет строку по разделителям, не заходя внутрь скобок и кавычек «…»."""
    parts, buf, depth, quoted = [], [], 0, False
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "«":
            quoted = True
        elif ch == "»":
            quoted = False
        if ch in separators and depth == 0 and not quoted:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return [p.strip(" .,;") for p in parts if p.strip(" .,;")]


def _last_top_level_paren(text: str) -> tuple[str, str] | None:
    """«Имя (профиль, II ур.)» -> ('Имя ', 'профиль, II ур.')"""
    s = text.rstrip(" .;")
    if not s.endswith(")"):
        return None
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        if s[i] == ")":
            depth += 1
        elif s[i] == "(":
            depth -= 1
            if depth == 0:
                return s[:i], s[i + 1 : -1]
    return None


def _parse_attrs(text: str) -> tuple[str, str, str, str]:
    """'инженерные науки, II ур.' -> (профиль, уровень, кому, класс)"""
    profile_parts: list[str] = []
    level = role = grade = ""
    for token in split_top_level(clean_text(text), ",;"):
        low = token.lower().replace("ё", "е")
        if not low or low == "?":
            continue
        lvl = norm_level(token)
        if not lvl:
            m = RE_LEVEL_TAIL.search(token)
            if m:
                lvl = ROMAN.get(m.group(1), "")
        if lvl and len(token) <= 24:
            level = level or lvl
            continue
        if "поб" in low or "приз" in low:
            role = role or norm_role(token)
            continue
        if re.search(r"\bкл(асс|\.)", low):
            grade = grade or clean_text(token)
            continue
        profile_parts.append(clean_text(token))
    return ", ".join(profile_parts), level, role, grade


# граница разделов «Информатика: … . Математика: … . ИИ (…) — …»: точка и слово с заглавной
# («побед. и призёры», «Всерос. олимпиада» с маленькой буквы границей не считаются)
_RE_SECTION_BOUNDARY = re.compile(r"(?<=[а-яё)»])\.\s+(?=[А-ЯЁ])")
SUBJECT_LISTS_MARKER = "поимённый список олимпиад"


def _parse_subject_lists(s: str) -> list[ParsedCondition]:
    """
    Формат ИТМО «Предмет: олимпиады — условие; олимпиады — условие. Другой предмет: …»:

    «Информатика: Высшая проба, Московская — I ур., побед. и призёры; Ломоносов — только победители»
    -> [('Высшая проба', 'Информатика', 'I', 'победители и призёры'), ('Московская', …),
        ('Ломоносов', 'Информатика', '', 'только победители')]

    Общий разбор режет такой текст по «;» и теряет названия (в имя попадал заголовок, а часть
    олимпиад — МОШ, ПВГ, НТО, ЮМШ — пропадала).
    """
    start = s.lower().find(SUBJECT_LISTS_MARKER) + len(SUBJECT_LISTS_MARKER)
    body = s[start:].lstrip(". ")
    out: list[ParsedCondition] = []
    for section in _RE_SECTION_BOUNDARY.split(body):
        section = section.strip().rstrip(".")
        colon, paren = section.find(":"), section.find("(")
        if colon > 0 and (paren == -1 or colon < paren):
            subject, rest = clean_text(section[:colon]), section[colon + 1 :]
        else:
            # «ИИ (Всерос. олимпиада по ИИ) — победители»: предмет, олимпиада в скобках
            m = re.match(r"^([^(—]+?)\s*\(([^)]*)\)\s*(—.*)$", section)
            if not m:
                continue
            subject, rest = clean_text(m.group(1)), f"{m.group(2)} {m.group(3)}"
        for group in split_top_level(rest, ";"):
            names_part, sep, tail = group.partition("—")
            if not sep:
                continue
            _, level, role, grade = _parse_attrs(tail)
            for name in split_top_level(names_part, ","):
                name = clean_text(name)
                if name:
                    out.append(
                        ParsedCondition(
                            name=name,
                            profile=subject.lower(),
                            level=level,
                            role=role,
                            grade=grade,
                            raw=clean_text(f"{subject}: {group}")[:300],
                            exact=True,
                        )
                    )
    return out


def parse_enumeration(text: str) -> list[ParsedCondition]:
    """
    Превращает сводную формулировку из «Базы» в строки таблицы:

    «[143 вар.] «Высшая проба» (информатика, I ур.); «Ломоносов» (математика, I ур.)»
    -> [('«Высшая проба»', 'информатика', 'I'), ('«Ломоносов»', 'математика', 'I')]

    Поддерживает и формат ВШЭ («олимпиада»: профиль (поб.+приз., 11 кл.), …),
    и формулировки МГУ («A, B, C — уровень I, 11 класс, победитель и призёр»).
    """
    s = clean_text(text)
    if not s or s in ("—", "-", "–"):
        return []
    s = RE_BRACKET_PREFIX.sub("", s)
    if SUBJECT_LISTS_MARKER in s.lower():
        parsed = _parse_subject_lists(s)
        if parsed:
            return parsed
    default_role = ""
    m = RE_ROLE_PREFIX.match(s)
    if m:
        default_role = norm_role(m.group(1))
        s = s[m.end() :]

    out: list[ParsedCondition] = []
    for item in split_top_level(s, ";"):
        head, groups = item, []

        colon = item.find(":")
        paren = item.find("(")
        if colon > 0 and (paren == -1 or colon < paren) and len(item[:colon]) < 160:
            head = item[:colon]
            groups = split_top_level(item[colon + 1 :], ",")
        else:
            split = _last_top_level_paren(item)
            if split:
                head, group = split
                groups = [group]

        tail_profile = tail_level = tail_role = tail_grade = ""
        if "—" in head or " – " in head:
            head, _, tail = head.partition("—" if "—" in head else " – ")
            tail_profile, tail_level, tail_role, tail_grade = _parse_attrs(tail)

        if not groups:
            groups = [""]
        for group in groups:
            profile, level, role, grade = ("", "", "", "")
            if group:
                inner = _last_top_level_paren(group)
                if inner:
                    profile_head, attrs = inner
                    profile, level, role, grade = _parse_attrs(attrs)
                    profile = clean_text(profile_head) or profile
                else:
                    profile, level, role, grade = _parse_attrs(group)
            out.append(
                ParsedCondition(
                    name=clean_text(head),
                    profile=profile or tail_profile,
                    level=level or tail_level,
                    role=role or tail_role or default_role,
                    grade=grade or tail_grade,
                    raw=clean_text(item)[:300],
                )
            )
    return out


# --------------------------------------------------------------------------
# правила вида «любая олимпиада перечня по профилю X»
# --------------------------------------------------------------------------

RULE_TRIGGERS = (
    "любая олимпиада перечн",
    "любые олимпиады",
    "любой олимпиады перечн",
    "все технологические профили",
    "перечневые олимпиады",
    "олимпиады перечня",
    "олимпиада перечня",
    "весь перечень",
    "всех уровней",
)

# сокращения, которыми вузы называют профили перечня
PROFILE_SYNONYMS = {
    "икт": "информационные и коммуникационные технологии",
    "ии": "искусственный интеллект",
    "иб": "информационная безопасность",
    "финтех": "программная инженерия в финансовых технологиях",
    "промпрограммирование": "промышленное программирование",
    "промышленное программирование": "промышленное программирование",
    "космоснимки": "космические системы",
    "аэрокосмос": "аэрокосмические системы",
    "мобильные приложения": "разработка мобильных приложений",
    "разработка мобильных предложений": "разработка мобильных приложений",
    "большие данные": "большие данные и машинное обучение",
    "нейротехнологии": "нейротехнологии и когнитивные науки",
    "беспроводная связь": "технологии беспроводной связи",
    "передовые производств. технологии": "передовые производственные технологии",
    "матмоделирование+ии": "математическое моделирование и искусственный интеллект",
    "матмоделирование": "математическое моделирование и искусственный интеллект",
    "разработка игр": "разработка компьютерных игр",
    "виртуальные миры": "виртуальные миры",
    "умные системы": "умные системы и технологии",
    "робото-профили": "интеллектуальные робототехнические системы",
    "беспилотники": "беспилотные авиационные системы",
    "водные": "водные робототехнические системы",
    "автономные транспортные": "автономные транспортные системы",
    "интеллект. энерг. системы": "интеллектуальные энергетические системы",
    "интеллект. робототехн. системы": "интеллектуальные робототехнические системы",
    "компьютерная безопасность": "компьютерная безопасность",
    "ин.язык": "иностранный язык",
    "английский/иностранный": "иностранный язык",
    "инженерное дело/науки": "инженерное дело",
    "анализ данных и матмоделирование+ии": "анализ данных",
}

# то, что точно не является профилем олимпиады
RULE_STOPWORDS = (
    "олимпиад",
    "бви",
    "балл",
    "побед",
    "призёр",
    "призер",
    "перечн",
    "класс",
    "егэ",
    "уровн",
    " ур",
    "диплом",
    "подтвержд",
    "направлен",
    "программ приёма",
    "поимённо",
    "поименно",
    "плюс",
    "также",
    "щедро",
    "самое",
    "отдельно",
    "только на",
    "для ",
    "если",
    "ду",
    "вступительн",
    "конкурс",
    "год",
    "сборн",
    "финал",
)

RE_LEVEL_RANGE = re.compile(
    r"\(?\b(I{1,3})\s*[–—-]\s*(I{1,3})\b\)?|\(?\b(I{1,3})\b\s*(?:ур\.?|уров\w*)?\)?",
    re.IGNORECASE,
)

# «ЩЕДРО: любая олимпиада перечня I–III уровня по …» — служебная часть правила
RE_RULE_PREFIX = re.compile(
    r".*?(?:люб\w+\s+олимпиад\w*\s+перечн\w*|люб\w+\s+олимпиад\w*|перечневые\s+олимпиады"
    r"|все\s+технологические\s+профили|олимпиад\w*\s+перечня)"
    r"(?:[^,;:]{0,60}?(?:уровн\w*|ур\.?))?\s*(?:по\s+профил\w*|по|:)?\s*",
    re.IGNORECASE,
)

# сокращения, после которых точка не заканчивает предложение
ABBREVIATIONS = {
    "им",
    "ур",
    "поб",
    "приз",
    "др",
    "т",
    "п",
    "г",
    "гг",
    "кл",
    "проф",
    "всерос",
    "мин",
    "обл",
    "производств",
    "гос",
    "напр",
    "см",
    "ин",
    "мат",
    "техн",
    "спец",
}
RE_SENTENCE_BREAK = re.compile(r"[.;]\s+")
RE_LAST_WORD = re.compile(r"([А-Яа-яЁёA-Za-z]+)\.?$")


def split_sentences(text: str) -> list[str]:
    """Режет текст на предложения, не ломая «побед.», «ур.», «производств. технологии»."""
    s = clean_text(text)
    out: list[str] = []
    start = 0
    for m in RE_SENTENCE_BREAK.finditer(s):
        nxt = s[m.end() : m.end() + 1]
        if m.group(0)[0] != ";" and not (nxt.isupper() or nxt == "«"):
            continue
        word = RE_LAST_WORD.search(s[start : m.start() + 1])
        if m.group(0)[0] != ";" and (word.group(1).lower() if word else "") in ABBREVIATIONS:
            continue
        out.append(s[start : m.start()])
        start = m.end()
    out.append(s[start:])
    return [p.strip(" .;") for p in out if p.strip(" .;")]


@dataclass
class ProfileRule:
    """«ИКТ (II–III) — побед. и призёры» -> профили, уровни, кому."""

    profiles: list[str]
    levels: list[str] = field(default_factory=list)
    role: str = ""
    raw: str = ""
    # rsosh — только олимпиады перечня, vsosh — только ВсОШ, any — любые
    scope: str = "any"
    # предметы ЕГЭ для подтверждения: «Астрономия (подтв.: математика, физика)» -> [математика, физика]
    confirm: list[str] = field(default_factory=list)
    # олимпиады целиком: «НТО (все профили)» -> ["НТО"]; профили берутся из справочника
    whole_olympiads: list[str] = field(default_factory=list)


def has_profile_rule(text: str) -> bool:
    low = clean_text(text).lower().replace("ё", "е")
    return any(t.replace("ё", "е") in low for t in RULE_TRIGGERS)


def _levels_in(text: str) -> list[str]:
    """'(I–III)' -> ['I','II','III'];  '(II)' -> ['II']"""
    order = ["I", "II", "III"]
    found: list[str] = []
    for m in RE_LEVEL_RANGE.finditer(clean_text(text)):
        if m.group(1) and m.group(2):
            a, b = m.group(1).upper(), m.group(2).upper()
            if a in order and b in order:
                lo, hi = sorted((order.index(a), order.index(b)))
                found.extend(order[lo : hi + 1])
        elif m.group(3):
            token = m.group(3).upper()
            if token in order:
                found.append(token)
    return sorted(set(found), key=order.index)


def _looks_like_profile(token: str) -> bool:
    low = clean_text(token).lower().replace("ё", "е")
    if len(low) < 3 or len(low) > 70:
        return False
    return not any(word in low for word in RULE_STOPWORDS)


# «(подтв.: математика, физика)» — предметы ЕГЭ для подтверждения диплома, а не профили
RE_CONFIRM_GROUP = re.compile(r"\(\s*подтв\w*\.?\s*:?\s*([^()]*)\)", re.IGNORECASE)
# «НТО (все профили)» — вся олимпиада, а не профиль «все профили»
RE_ALL_PROFILES = re.compile(r"([^,;()|]+?)\s*\(\s*все\s+профили\s*\)", re.IGNORECASE)


def parse_profile_rules(text: str) -> list[ProfileRule]:
    """
    Разбирает правила, заданные профилем олимпиады, а не её названием:

    «любая олимпиада перечня: математика, физика, астрономия (I–III);
      естественные науки, наносистемы (II–III) — побед. и призёры БВИ»
    """
    s = clean_text(text)
    if not s or not has_profile_rule(s):
        return []

    default_scope = "rsosh" if "перечн" in s.lower() else "any"

    rules: list[ProfileRule] = []
    # «… профили: Робототехника (подтв.: …) | ВсОШ (финал): …» — после «|» другое правило
    chunks = [
        part.strip()
        for sentence in split_sentences(s)
        for part in sentence.split("|")
        if part.strip()
    ]
    for full_chunk in chunks:
        # скобки «(подтв.: …)» и «(все профили)» — не перечисление профилей: забираем их отдельно
        confirm = [
            clean_text(w).strip(" .;:")
            for m in RE_CONFIRM_GROUP.finditer(full_chunk)
            for w in m.group(1).split(",")
            if clean_text(w).strip(" .;:")
        ]
        chunk = RE_CONFIRM_GROUP.sub("", full_chunk)
        whole_olympiads = [
            clean_text(RE_RULE_PREFIX.sub("", m.group(1), count=1)).strip(" .;:")
            for m in RE_ALL_PROFILES.finditer(chunk)
        ]
        whole_olympiads = [w for w in whole_olympiads if w]
        chunk = RE_ALL_PROFILES.sub("", chunk)
        low = chunk.lower().replace("ё", "е")
        if "всош" in low or "заключительный этап" in low:
            scope = "vsosh"
        elif "перечн" in low:
            scope = "rsosh"
        else:
            scope = default_scope
        levels = _levels_in(chunk)
        role = (
            norm_role(chunk)
            if ("побед" in chunk.lower() or "призёр" in chunk.lower() or "призер" in chunk.lower())
            else ""
        )
        # перечисление в скобках: «все технологические профили (a, b, c)»
        groups = re.findall(r"\(([^()]{10,400})\)", chunk)
        source = groups[0] if groups else chunk
        source = RE_RULE_PREFIX.sub(
            "", source, count=1
        )  # «любая олимпиада перечня I–III уровня по»
        source = re.sub(r"^[^:]{0,80}:", "", source)  # «любая олимпиада перечня:»
        source = re.sub(r"—.*$", "", source)  # хвост «— побед. и призёры БВИ»
        source = re.sub(r"\([^()]*\)", " ", source)  # уровни в скобках
        tokens: list[str] = []
        for part in re.split(r"[,/]| и (?=[а-яё])", source):
            part = clean_text(part).strip(" .;:")
            part = re.sub(r"\b(I{1,3})\b\s*(ур\.?|уров\w*)?", "", part).strip(" .;:")
            if _looks_like_profile(part):
                tokens.append(part)
        if tokens or whole_olympiads:
            rules.append(
                ProfileRule(
                    profiles=tokens,
                    levels=levels,
                    role=role,
                    raw=full_chunk[:200],
                    scope=scope,
                    confirm=confirm,
                    whole_olympiads=whole_olympiads,
                )
            )
    return rules


# --------------------------------------------------------------------------
# сопоставление названий профилей (склонения и сокращения)
# --------------------------------------------------------------------------

STEM_LEN = 6


def profile_stems(name: str) -> tuple[str, ...]:
    words = [
        w
        for w in re.split(r"[^а-яёa-z0-9]+", clean_text(name).lower().replace("ё", "е"))
        if len(w) > 2
    ]
    return tuple(sorted({w[:STEM_LEN] for w in words}))


class ProfileIndex:
    """Ищет профиль в справочнике по «человеческому» написанию из правил вуза."""

    def __init__(self) -> None:
        self._exact: dict[str, list[int]] = {}
        self._stems: list[tuple[tuple[str, ...], int]] = []

    def add(self, profile_id: int, name: str) -> None:
        self._exact.setdefault(squash(name), []).append(profile_id)
        stems = profile_stems(name)
        if stems:
            self._stems.append((stems, profile_id))

    def find(self, query: str) -> list[int]:
        raw = clean_text(query).lower().replace("ё", "е").strip(" .;:")
        query = PROFILE_SYNONYMS.get(raw, raw)
        # у сокращений из справочника допускаем более длинное официальное название
        max_diff = 8 if query != raw else 3
        key = squash(query)
        if key in self._exact:
            return list(self._exact[key])
        stems = profile_stems(query)
        if not stems:
            return []
        best, best_diff = [], 99
        for candidate, profile_id in self._stems:
            if not set(stems).issubset(candidate):
                continue
            diff = len(candidate) - len(stems)
            if diff < best_diff:
                best, best_diff = [profile_id], diff
            elif diff == best_diff:
                best.append(profile_id)
        return best if best_diff <= max_diff else []


def split_segments(text: str) -> list[str]:
    """Режем длинное описание условий на смысловые куски."""
    s = clean_text(text)
    if not s:
        return []
    parts = re.split(r"[;\n]|(?<=[»\)])\s*,\s*(?=[А-ЯA-Z«])", s)
    return [p.strip() for p in parts if p and p.strip()]


# --------------------------------------------------------------------------
# поиск названий олимпиад в тексте
# --------------------------------------------------------------------------


@dataclass
class AliasEntry:
    olympiad_id: int
    alias: str
    squashed: str
    is_generic: bool = False


@dataclass
class OlympiadHit:
    olympiad_id: int
    alias: str
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


class OlympiadMatcher:
    """
    Ищет названия олимпиад в свободном тексте по «схлопнутым» алиасам.

    Правила:
      * более длинное совпадение побеждает вложенное более короткое;
      * «общие» алиасы (всош, всерос, олимпиада школьников СПбГУ без уточнения)
        снимаются, если рядом стоит конкретное название перечневой олимпиады
        («Всероссийская олимпиада школьников «Высшая проба»»).
    """

    def __init__(self) -> None:
        self._aliases: list[AliasEntry] = []
        self._by_squashed: dict[str, AliasEntry] = {}
        self._cache: dict[str, list[OlympiadHit]] = {}
        self._dirty = True

    def add(self, olympiad_id: int, alias: str, is_generic: bool = False) -> None:
        sq = squash(alias)
        if len(sq) < 4:
            return
        existing = self._by_squashed.get(sq)
        if existing is not None:
            # тот же ключ уже занят — не плодим дубликаты
            if existing.olympiad_id == olympiad_id and is_generic == existing.is_generic:
                return
            if existing.olympiad_id != olympiad_id:
                # неоднозначный алиас: помечаем как общий, чтобы не ловил лишнего
                existing.is_generic = True
                return
            return
        entry = AliasEntry(olympiad_id, clean_text(alias), sq, is_generic)
        self._aliases.append(entry)
        self._by_squashed[sq] = entry
        self._dirty = True
        self._cache.clear()

    def _prepare(self) -> None:
        if self._dirty:
            self._aliases.sort(key=lambda a: len(a.squashed), reverse=True)
            self._dirty = False

    def exact(self, name: str) -> int | None:
        entry = self._by_squashed.get(squash(name))
        return entry.olympiad_id if entry else None

    def find(self, text: str) -> list[OlympiadHit]:
        sq = squash(text)
        if not sq:
            return []
        cached = self._cache.get(sq)
        if cached is not None:
            return cached
        self._prepare()

        hits: list[OlympiadHit] = []
        for entry in self._aliases:
            start = sq.find(entry.squashed)
            while start != -1:
                hits.append(
                    OlympiadHit(entry.olympiad_id, entry.alias, start, start + len(entry.squashed))
                )
                start = sq.find(entry.squashed, start + 1)

        hits.sort(key=lambda h: (-h.length, h.start))
        kept: list[OlympiadHit] = []
        for hit in hits:
            if any(k.start <= hit.start and hit.end <= k.end for k in kept):
                continue  # вложено в более длинное совпадение
            kept.append(hit)

        # снимаем «общие» алиасы, если сразу за ними идёт конкретное название
        specific = [h for h in kept if not self._is_generic(h)]
        result: list[OlympiadHit] = []
        for hit in kept:
            if self._is_generic(hit) and any(
                s is not hit and s.start >= hit.start and s.start - hit.end <= 4 and s.end > hit.end
                for s in specific
            ):
                continue
            result.append(hit)

        result.sort(key=lambda h: h.start)
        # по одной записи на олимпиаду
        seen = set()
        unique: list[OlympiadHit] = []
        for hit in result:
            if hit.olympiad_id in seen:
                continue
            seen.add(hit.olympiad_id)
            unique.append(hit)

        self._cache[sq] = unique
        return unique

    def _is_generic(self, hit: OlympiadHit) -> bool:
        entry = self._by_squashed.get(squash(hit.alias))
        return bool(entry and entry.is_generic)
