"""Проверка ответа помощника по фактам диалога (оценка E1, затем проверка в проде V2).

Факты диалога — всё, что вернули инструменты (строки и числа из их JSON), и всё, что написал
сам ученик. Ответ проверяется на три вида нарушений:

- `entity` — назван вуз или олимпиада из словаря базы, которых нет в фактах;
- `number` — «фактическое» число (порог ЕГЭ, класс, уровень олимпиады, число вузов или
  направлений), которого нет в фактах;
- `hedge` — догадка («обычно», «как правило», «скорее всего»…) в предложении про олимпиаду, вуз
  или с числом.

Детектор ошибается в сторону ловли выдумок, но короткие и двусмысленные названия (общие слова,
предметы, «НИУ», трёхбуквенные сокращения строчными) не дают срабатываний. Логика чистая: без БД
и сети; словарь из базы загружает отдельная функция `load_vocabulary`.
"""

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from olymp_domain import squash
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import data_version, fetch_all

EntityKind = Literal["university", "olympiad"]
ViolationKind = Literal["entity", "number", "hedge"]


@dataclass(frozen=True)
class Entity:
    kind: EntityKind
    id: int
    label: str


@dataclass(frozen=True)
class Mention:
    """Упоминание в тексте: одно название может означать несколько сущностей (СПбГУ — и вуз,
    и олимпиада; ВШЭ — четыре кампуса)."""

    fragment: str
    start: int
    end: int
    entities: frozenset[Entity]


@dataclass(frozen=True)
class Violation:
    kind: ViolationKind
    fragment: str
    sentence: str
    detail: str

    def __str__(self) -> str:
        return f"{self.detail}: «{self.fragment}» в «{self.sentence}»"


# ---------------------------------------------------------------- слова и токены

_TOKEN = re.compile(r"[^\W_]+")
_QUOTES_OPEN = "«\"„“'"
_QUOTES_CLOSE = "»\"“”'"

# Слова, из которых одних не складывается название: служебные, организационные, предметы.
# Название только из таких слов («Олимпиада по ИИ», «Юный историк», «Всероссийская олимпиада»)
# в словарь не попадает: оно совпало бы с обычной фразой ответа.
_FUNCTION_WORDS = frozenset(
    [
        "и",
        "в",
        "во",
        "по",
        "для",
        "на",
        "с",
        "со",
        "из",
        "к",
        "о",
        "об",
        "при",
        "а",
        "или",
        "им",
        "имени",
        "не",
        "все",
        "ии",
        "рф",
        "г",
        "ф",
    ]
)
_GENERIC_STEMS = (
    "олимпиад", "школьн", "турнир", "конкурс", "фестивал", "всеросс", "межрегион", "междунар",
    "открыт", "инженер", "университет", "институт", "академи", "государствен", "национальн",
    "исследоват", "федеральн", "техническ", "технолог", "факультет", "школ", "этап", "заключит",
    "финал", "перечн", "полное", "наименован", "вузовск", "предметн", "многопрофил", "командн",
    "математ", "физик", "физическ", "хими", "биолог", "информат", "программ", "истори",
    "обществозн", "литератур", "русск", "язык", "иностран", "английск", "экономи", "прав",
    "географ", "астроном", "эколог", "искусств", "культур", "архитектур", "дизайн", "робот",
    "филолог", "лингвист", "философ", "социолог", "психолог", "журналист", "интеллект",
    "естествозн", "энергет", "машиностр", "аудит", "безопасн", "финанс", "проект", "наук",
    "научн", "указан", "юный", "юных", "юного", "ниу", "нияу", "ниту", "филиал",
)  # fmt: skip
# Однословные названия, которые совпадают с обычными словами: засчитываются только в кавычках
_COMMON_WORDS = frozenset(
    [
        "логично",
        "грани",
        "звезда",
        "изумруд",
        "газпром",
        "росатом",
        "нанотехнологии",
        "ключ",
        "время",
        "икра",
        "бельчонок",
    ]
)
# Сокращения-приставки в названиях вузов: сами по себе вуз не называют
_GENERIC_ABBREVIATIONS = frozenset(
    ["ниу", "нияу", "ниту", "мид", "рф", "ано", "во", "фгбоу", "фгаоу", "ii", "iii"]
)
# после этих слов двусмысленное название («СПбГУ», «МФТИ») — вуз, а не олимпиада
_PLACE_WORDS = frozenset(
    ["в", "во", "из", "вуз", "вузе", "вуза", "университет", "университете", "поступить"]
)


def _norm(token: str) -> str:
    return token.lower().replace("ё", "е")


def _tokens(text: str) -> list[str]:
    return [_norm(m.group()) for m in _TOKEN.finditer(text)]


def _is_generic(token: str) -> bool:
    return token in _FUNCTION_WORDS or token.startswith(_GENERIC_STEMS)


def _is_abbreviation(word: str) -> bool:
    """«ВШЭ», «СПбГУ», «УрФУ», «РАНХиГС»: не меньше двух прописных букв."""
    return sum(ch.isupper() for ch in word) >= 2


def _token_match(alias: str, token: str) -> bool:
    """Слово ответа — форма слова названия: «Высшей пробы» ~ «Высшая проба»."""
    if len(alias) <= 4 or alias.isdigit():
        return token == alias
    stem = alias[: max(4, len(alias) - 2)]
    return token.startswith(stem) and len(token) <= len(alias) + 3


@dataclass(frozen=True)
class _Term:
    tokens: tuple[str, ...]
    abbreviation: bool  # одно короткое слово: только прописными («МГУ», «НТО»)
    single: bool  # одно слово: только с прописной буквы
    quoted: bool  # обычное слово («Звезда»): только в кавычках


def university_names(name: str, short_name: str = "") -> list[str]:
    """Как вуз называют в тексте: полное и краткое название, сокращения из него.

    «НИУ ВШЭ — Пермь» → «НИУ ВШЭ», «ВШЭ»; «МГУ им. М.В. Ломоносова» → «МГУ»;
    «Казанский (Приволжский) федеральный университет (КФУ)» → «КФУ»; «Университет ИТМО» →
    «ИТМО». Города в скобках («(Москва)») названиями не считаются.
    """
    out: list[str] = []
    for value in (name, short_name):
        value = (value or "").strip()
        if not value or value.endswith("…"):
            continue
        out.append(value)
        for inner in re.findall(r"\(([^)]*)\)", value):
            inner = inner.split(",")[0].strip()
            if _is_abbreviation(inner) or re.search(r"университет|академи", inner, re.I):
                out.append(inner)
        base = re.sub(r"\([^)]*\)", " ", value)
        base = re.split(r"\s+[—–-]\s+|\s+им\.|\s+имени\s", base)[0].strip()
        if base and base != value:
            out.append(base)
        out.append(re.sub(r"^Университет\s+", "", base))
        out += [
            word
            for word in re.findall(r"[^\W_]+", value)
            if _is_abbreviation(word)
            and len(word) >= 3
            and _norm(word) not in _GENERIC_ABBREVIATIONS
        ]
    return list(dict.fromkeys(item for item in out if item))


class Vocabulary:
    """Известные названия вузов и олимпиад. Сравнение — по словам с учётом окончаний."""

    def __init__(self) -> None:
        self._terms: dict[_Term, set[Entity]] = {}
        self._index: dict[str, list[_Term]] = {}
        self._keys: dict[Entity, set[str]] = {}

    def __len__(self) -> int:
        return len(self._terms)

    def add(self, entity: Entity, *names: str, full: bool = True) -> None:
        """Добавляет названия сущности. Короткие и общие названия пропускаются.

        full=False — производные названия («ВШЭ» из «НИУ ВШЭ — Пермь»): по ним сущность
        находится в ответе, но в фактах она ищется только по словам, а не по склейке букв.
        """
        for name in names:
            term = self._term(name or "")
            if term is None:
                continue
            if term not in self._terms:
                self._terms[term] = set()
                self._index.setdefault(term.tokens[0][:4], []).append(term)
            self._terms[term].add(entity)
            key = squash(name)
            if full and len(key) >= 8:
                self._keys.setdefault(entity, set()).add(key)

    def add_university(self, id_: int, name: str, short_name: str = "") -> None:
        entity = Entity("university", id_, short_name or name)
        self.add(entity, name, short_name)
        self.add(entity, *university_names(name, short_name), full=False)

    @staticmethod
    def _term(name: str) -> "_Term | None":
        name = name.strip()
        if name.endswith("…"):
            return None  # обрезанное краткое название вуза
        tokens = tuple(_tokens(name))
        if not tokens or len(squash(name)) < 3 or all(_is_generic(t) for t in tokens):
            return None
        single = len(tokens) == 1
        if single and tokens[0] in _GENERIC_ABBREVIATIONS:
            return None
        return _Term(
            tokens,
            abbreviation=single and len(tokens[0]) <= 3,
            single=single,
            quoted=single and tokens[0] in _COMMON_WORDS,
        )

    def find(self, text: str, *, strict: bool = True) -> list[Mention]:
        """Названия в тексте; более длинное совпадение побеждает вложенное.

        strict=False — без требований к регистру и кавычкам: так ищутся названия в фактах
        (ученик пишет «мгу» строчными, и это всё равно МГУ).
        """
        found = list(_TOKEN.finditer(text))
        words = [_norm(m.group()) for m in found]
        candidates: list[tuple[int, int, _Term]] = []
        for i, word in enumerate(words):
            for term in self._index.get(word[:4], ()):
                n = len(term.tokens)
                if i + n > len(words):
                    continue
                if not all(_token_match(term.tokens[j], words[i + j]) for j in range(n)):
                    continue
                if strict and not self._allowed(term, text, found[i], found[i + n - 1]):
                    continue
                if _after_namesake(words, i):
                    continue  # «МГУ им. М.В. Ломоносова»: фамилия в названии, а не олимпиада
                candidates.append((i, i + n, term))
        candidates.sort(key=lambda c: (-(c[1] - c[0]), c[0]))
        taken: set[int] = set()
        mentions: list[Mention] = []
        for start, end, term in candidates:
            if taken & set(range(start, end)):
                continue
            taken.update(range(start, end))
            left, right = found[start].start(), found[end - 1].end()
            entities = frozenset(self._terms[term])
            universities = frozenset(e for e in entities if e.kind == "university")
            if universities and start and words[start - 1] in _PLACE_WORDS:
                entities = universities  # «льготы в МФТИ» — вуз, а не олимпиада «Физтех»
            mentions.append(Mention(text[left:right], left, right, entities))
        return sorted(mentions, key=lambda m: m.start)

    @staticmethod
    def _allowed(term: _Term, text: str, first: re.Match[str], last: re.Match[str]) -> bool:
        word = first.group()
        if term.abbreviation and not _is_abbreviation(word):
            return False
        if term.single and not word[0].isupper():
            return False
        if term.quoted:
            before = text[max(0, first.start() - 2) : first.start()]
            after = text[last.end() : last.end() + 2]
            return any(q in before for q in _QUOTES_OPEN) and any(q in after for q in _QUOTES_CLOSE)
        return True

    def known(self, facts: "Facts") -> set[Entity]:
        """Сущности, которые есть в фактах диалога."""
        found = {e for m in self.find(facts.text, strict=False) for e in m.entities}
        key = facts.squashed
        found |= {e for e, keys in self._keys.items() if any(k in key for k in keys)}
        return found


def _after_namesake(words: list[str], i: int) -> bool:
    j = i - 1
    while j >= 0 and len(words[j]) == 1:  # инициалы
        j -= 1
    return j >= 0 and words[j] in ("им", "имени")


async def load_vocabulary(session: AsyncSession) -> Vocabulary:
    """Словарь из базы: вузы, олимпиады и их алиасы."""
    vocab = Vocabulary()
    for row in await fetch_all(session, "SELECT id, name, short_name FROM universities"):
        vocab.add_university(row["id"], row["name"], row["short_name"])
    olympiads: dict[int, Entity] = {}
    for row in await fetch_all(session, "SELECT id, short_name, canonical_name FROM olympiads"):
        entity = Entity("olympiad", row["id"], row["short_name"] or row["canonical_name"])
        olympiads[row["id"]] = entity
        vocab.add(entity, row["short_name"], row["canonical_name"])
    for row in await fetch_all(session, "SELECT olympiad_id, alias FROM olympiad_aliases"):
        if row["olympiad_id"] in olympiads:
            vocab.add(olympiads[row["olympiad_id"]], row["alias"])
    return vocab


class VocabularyCache:
    """Словарь грузится из базы один раз и живёт до пересборки базы (меняется data_version)."""

    def __init__(self) -> None:
        self.version: str | None = None
        self.vocab: Vocabulary | None = None

    async def get(self, session: AsyncSession) -> Vocabulary:
        version = await data_version(session)
        if self.vocab is None or version != self.version:
            self.vocab = await load_vocabulary(session)
            self.version = version
        return self.vocab


# ---------------------------------------------------------------- факты

_ROMAN = {"I": 1, "II": 2, "III": 3}
_DASH = r"[-–—−]"
_ID_KEYS = re.compile(r"(^|_)id$")
_GRADE_KEYS = re.compile(r"grade|class", re.I)
_CODE = re.compile(r"\d+(?:\.\d+)+")  # коды направлений 01.03.02 и даты — не факты-числа


def _roman_levels(text: str) -> set[int]:
    return {_ROMAN[m] for m in re.findall(r"(?<![A-Za-z])(I{1,3})(?![A-Za-z])", text)}


def _grade_range(text: str) -> set[int]:
    """Все числа «9–11» и «9, 10» как классы 1–11."""
    out = {int(n) for n in re.findall(r"\d{1,2}", text) if 1 <= int(n) <= 11}
    for a, b in re.findall(rf"(?<!\d)(\d{{1,2}})\s*{_DASH}\s*(\d{{1,2}})(?!\d)", text):
        if 1 <= int(a) < int(b) <= 11:
            out |= set(range(int(a), int(b) + 1))
    return out


@dataclass
class Facts:
    """Что разрешено говорить в диалоге: результаты инструментов и слова самого ученика.

    numbers — все числа фактов (кроме id и кодов направлений вида 01.03.02); grades — только
    классы: из полей grade/grades, из фраз «9–11 класс» и из слов ученика. Иначе «9 класс»
    в ответе оправдывало бы любое «programs": 9.
    """

    texts: list[str] = field(default_factory=list)
    numbers: set[int] = field(default_factory=set)
    grades: set[int] = field(default_factory=set)
    levels: set[int] = field(default_factory=set)

    @classmethod
    def collect(cls, tool_contents: Iterable[str], user_texts: Iterable[str] = ()) -> "Facts":
        facts = cls()
        for content in tool_contents:
            facts.add_tool_content(content)
        for text in user_texts:
            facts.add_user_text(text)
        return facts

    @property
    def text(self) -> str:
        return "\n".join(self.texts)

    @property
    def squashed(self) -> str:
        return squash(self.text)

    def add_tool_content(self, content: str) -> None:
        """Результат инструмента: JSON (строки и числа рекурсивно) или просто текст."""
        try:
            data = json.loads(content)
        except ValueError:
            self.add_text(content)
            return
        self._walk(data, "")

    def add_user_text(self, text: str) -> None:
        """Слова ученика: его числа разрешены в любом смысле («я в 9 классе»)."""
        self.add_text(text)
        self.grades |= {int(n) for n in re.findall(r"\d{1,2}", text) if 1 <= int(n) <= 11}

    def add_text(self, text: str, key: str = "") -> None:
        self.texts.append(text)
        plain = _CODE.sub(" ", text)
        self.numbers |= {int(n) for n in re.findall(r"\d{1,4}", plain)}
        if _GRADE_KEYS.search(key):
            self.grades |= _grade_range(plain)
        for match in [*_GRADE.finditer(plain), *_GRADE_AFTER.finditer(plain)]:
            self.grades |= _grade_range(match.group(0))
        self.levels |= _roman_levels(text)
        self.levels |= {int(n) for n in re.findall(r"(?<!\d)([123])\s*-?\w{0,2}\s+уровн", text)}
        if key == "level":
            self.levels |= {int(n) for n in re.findall(r"[123]", text)}

    def _walk(self, value: Any, key: str) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                self._walk(v, str(k))
        elif isinstance(value, list):
            for item in value:
                self._walk(item, key)
        elif isinstance(value, str):
            self.add_text(value, key)
        elif isinstance(value, bool) or value is None:
            return
        elif isinstance(value, int | float) and float(value).is_integer():
            if _ID_KEYS.search(key):
                return  # id в тексте ответа не нужен, а «12 вузов» из id — выдумка
            self.numbers.add(int(value))
            if key == "level":
                self.levels.add(int(value))
            if _GRADE_KEYS.search(key) and 1 <= value <= 11:
                self.grades.add(int(value))


# ---------------------------------------------------------------- числа в ответе

_SUFFIX = r"(?:\s*-?\s*(?:го|й|м|х|ый|ой|ом|ых|ий))?"
_GRADE = re.compile(
    rf"(?<![\d.,])(\d{{1,2}}{_SUFFIX}(?:\s*(?:{_DASH}|до|по|и|или|,|/)\s*\d{{1,2}}{_SUFFIX})*)"
    r"\s*(?:класс\w*|кл\b\.?)",
    re.I,
)
_GRADE_AFTER = re.compile(rf"класс\w*\s*[:—–-]?\s*(\d{{1,2}})\s*{_DASH}\s*(\d{{1,2}})(?!\d)", re.I)
_COUNT = re.compile(
    r"(?<![\d.,])(\d{1,4})\s+(?:вуз\w*|университет\w*|направлени\w*|программ\w*|институт\w*"
    r"|факультет\w*)",
    re.I,
)
_LEVEL = re.compile(
    rf"(?<![\w])((?:I{{1,3}}|[123]){_SUFFIX}(?:\s*(?:{_DASH}|и|или|,|/)\s*(?:I{{1,3}}|[123]){_SUFFIX})*)"
    r"\s*[Уу]ров\w*"
)
_LEVEL_AFTER = re.compile(r"[Уу]ров\w*\s*[:—–-]?\s*(I{1,3})(?![\w])")
_EGE_BEFORE = re.compile(
    r"(?:\bот|\bне\s+ниже|\bне\s+менее|\bминимум|\bмин\.|\bпорог\w*(?:\s+ЕГЭ)?(?:\s*[—:–-])?"
    r"|\bвыше|\bбольше|≥|>=|⩾|>)\s*(\d{2,3})(?!\d)(?!\s*(?:класс|кл\b|вуз|университет|направлен"
    r"|программ|институт|факультет|%|лет|год|руб|тыс|чел|мест|раз|уровн|час|мин))",
    re.I,
)
_POINTS = re.compile(r"(?<![\d.,])(\d{1,3})\s*(?:балл\w*|б\.)", re.I)


def _fact_numbers(text: str) -> Iterator[tuple[str, re.Match[str], list[int]]]:
    """(вид, совпадение, числа) для «фактических» чисел; каждое число — один раз."""
    used: set[int] = set()

    def fresh(match: re.Match[str]) -> bool:
        span = set(range(match.start(), match.end()))
        if span & used:
            return False
        used.update(span)
        return True

    for match in _GRADE.finditer(text):
        values = [int(n) for n in re.findall(r"\d+", match.group(1))]
        if all(1 <= v <= 11 for v in values) and fresh(match):
            yield "класс", match, values
    for match in _GRADE_AFTER.finditer(text):
        values = [int(match.group(1)), int(match.group(2))]
        if all(1 <= v <= 11 for v in values) and fresh(match):
            yield "класс", match, values
    for match in _COUNT.finditer(text):
        if fresh(match):
            yield "число вузов или направлений", match, [int(match.group(1))]
    for match in [*_LEVEL.finditer(text), *_LEVEL_AFTER.finditer(text)]:
        raw = re.findall(r"I{1,3}|[123]", match.group(1))
        if fresh(match):
            yield "уровень олимпиады", match, [_ROMAN.get(v) or int(v) for v in raw]
    for match in _POINTS.finditer(text):
        value = int(match.group(1))
        if value == 100:
            continue  # «100 баллов» — вид льготы, а не порог
        if fresh(match):
            yield "балл ЕГЭ", match, [value]
    for match in _EGE_BEFORE.finditer(text):
        value = int(match.group(1))
        word = match.group(0).lower()
        loose = word.startswith(("от", "выше", "больше"))
        if value > 100 or (loose and value < 30):
            continue
        if fresh(match):
            yield "балл ЕГЭ", match, [value]


# ---------------------------------------------------------------- догадки и предложения

_HEDGE = re.compile(
    r"(?<![а-яёa-z])(обычно|как\s+правило|скорее\s+всего|чаще\s+всего|наверняка|вероятнее\s+всего"
    r"|вероятно|как\s+известно|традиционно|как\s+обычно)(?![а-яё])",
    re.I,
)
_DOMAIN = re.compile(
    r"олимпиад|вуз|университет|институт|профил|этап|балл|ЕГЭ|БВИ|класс|льгот|направлени|секци"
    r"|формат|регистрац|диплом|призер|призёр|победител|отбор|уровн|поступ|экзамен|задани|тур\b"
    r"|дат[аеуы]|срок",
    re.I,
)
# граница предложения: знак конца и прописная/кавычка/цифра/маркер списка после него, или перенос
# строки; «им. Ломоносова» и инициалы «М.В. Ломоносова» предложение не обрывают
_SENTENCE_END = re.compile(
    r"(?<!\bим\.)(?<!\bИм\.)(?<!\b[А-ЯЁA-Z]\.)(?<=[.!?…])\s+(?=[А-ЯЁA-Z«\"(\d•*–—-])|\n+"
)


def sentences(text: str) -> list[tuple[int, int]]:
    """Границы предложений и строк списка."""
    spans, start = [], 0
    for match in _SENTENCE_END.finditer(text):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def _hedge_key(text: str) -> str:
    return " ".join(text.lower().split())


def check(answer: str, facts: Facts, vocab: Vocabulary) -> list[Violation]:
    """Нарушения в ответе: выдуманные вузы и олимпиады, числа и догадки."""
    spans = sentences(answer)

    def sentence_at(pos: int) -> tuple[int, int]:
        return next(((a, b) for a, b in spans if a <= pos < b), (0, len(answer)))

    def quote(pos: int) -> str:
        a, b = sentence_at(pos)
        return answer[a:b].strip()

    violations: list[Violation] = []
    mentions = vocab.find(answer)
    known = vocab.known(facts) if mentions else set()
    for mention in mentions:
        if not mention.entities & known:
            kinds = {e.kind for e in mention.entities}
            what = (
                "вуз" if kinds == {"university"} else "олимпиада" if kinds == {"olympiad"} else ""
            )
            detail = f"{what or 'вуз или олимпиада'} не из данных"
            violations.append(Violation("entity", mention.fragment, quote(mention.start), detail))
    for what, match, values in _fact_numbers(answer):
        allowed = {"уровень олимпиады": facts.levels, "класс": facts.grades}.get(
            what, facts.numbers
        )
        if any(v not in allowed for v in values):
            fragment = match.group(0).strip()
            violations.append(
                Violation("number", fragment, quote(match.start()), f"{what} не из данных")
            )
    quoted_hedges = {_hedge_key(m.group(0)) for m in _HEDGE.finditer(facts.text)}
    for match in _HEDGE.finditer(answer):
        if _hedge_key(match.group(0)) in quoted_hedges:
            continue  # оговорка есть в самих данных: справочник правил пишет «обычно не ниже 75»
        a, b = sentence_at(match.start())
        sentence = answer[a:b]
        factual = (
            any(a <= m.start < b for m in mentions)
            or re.search(r"\d", sentence)
            or _DOMAIN.search(sentence)
        )
        if factual:
            violations.append(Violation("hedge", match.group(0), sentence.strip(), "догадка"))
    unique: dict[tuple[str, str], Violation] = {}
    for item in violations:
        unique.setdefault((item.kind, item.fragment.lower()), item)
    return list(unique.values())


# ---------------------------------------------------------------- вырезание


_EMPTY_ITEM = re.compile(r"(?m)^[ \t]*(?:[-•*]|\d+[.)])[ \t]*$\n?")


def cut(answer: str, violations: Iterable[Violation]) -> str:
    """Ответ без предложений и строк списка с нарушениями. Пустая строка — вырезано всё."""
    bad = {item.sentence for item in violations}
    pieces: list[str] = []
    pos = 0
    for a, b in sentences(answer):
        if answer[a:b].strip() in bad:
            pieces.append(answer[pos:a])
            pos = b
    pieces.append(answer[pos:])
    text = _EMPTY_ITEM.sub("", "".join(pieces))
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if re.search(r"[^\W_]", text) else ""
