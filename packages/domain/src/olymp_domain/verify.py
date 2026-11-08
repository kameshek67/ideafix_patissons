"""Сверка строки льготы с документом вуза (F-07, T-087): чистая логика без сети и LLM.

Модель предлагает вердикт и цитату, а этот модуль решает, можно ли ему верить:
- выбирает страницы документа, где вообще упомянута олимпиада строки;
- разбирает ответ модели строго по схеме;
- ищет цитату на указанной странице — без найденной цитаты вердикт не засчитывается.
"""

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

# Итоговые статусы строки после сверки с документом вуза.
CONFIRMED = "confirmed"
CONTRADICTED = "contradicted"
NOT_FOUND = "not_found"
UNVERIFIED = "unverified"
NO_MENTION = "no_mention"
NO_DOCUMENT = "no_document"
ERROR = "error"
DRY_RUN = "dry_run"

MODEL_VERDICTS = (CONFIRMED, CONTRADICTED, NOT_FOUND)
# поля строки, о расхождении в которых может сообщить модель
FIELDS = (
    "benefit_type",
    "olympiad",
    "profile",
    "level",
    "winner_role",
    "grade",
    "confirm_subject",
    "min_ege",
    "program",
)

MIN_QUOTE_CHARS = 20  # после нормализации: короче — не доказательство
MAX_PAGES = 3
MAX_PROMPT_CHARS = 12_000
MAX_COMMENT_CHARS = 300
MAX_ALIASES = 12
MAX_ALIAS_WORDS = 8

_NOT_ALNUM = re.compile(r"[^0-9a-zа-я]+")
_WORD = re.compile(r"[a-zа-я0-9]+")


# перенос слова в PDF: «школь-\nников» → «школьников»
_HYPHENATION = re.compile(r"([a-zа-я])-[ \t]*\r?\n[ \t]*([a-zа-я])")


def _lower(text: str) -> str:
    low = text.lower().replace("ё", "е").replace("\xad", "")
    return _HYPHENATION.sub(r"\1\2", low)


def normalize(text: str) -> str:
    """Ключ для сравнения цитаты: только буквы и цифры, нижний регистр, ё → е.

    Так переносы строк, переносы слов («програм-\\nмирование»), кавычки, тире и пробелы,
    которые по-разному отдаёт извлечение текста из PDF, не мешают найти цитату.
    """
    return _NOT_ALNUM.sub("", _lower(text))


def quote_on_page(quote: str, page_text: str) -> bool:
    """Цитата дословно есть на странице (с точностью до normalize) и не слишком коротка."""
    key = normalize(quote)
    return len(key) >= MIN_QUOTE_CHARS and key in normalize(page_text)


def _stem(word: str) -> str:
    # русские окончания короткие: «московская» → «московск» найдёт и «московской»
    return word if len(word) <= 4 else word[: max(4, len(word) - 2)]


def phrase_pattern(phrase: str) -> re.Pattern[str] | None:
    """Шаблон фразы с учётом падежей: основы слов по порядку, между ними — знаки и пробелы.

    Одно короткое слово («МОШ», «НТО») ищется только целиком, иначе оно найдётся внутри
    других слов.
    """
    words = _WORD.findall(_lower(phrase))[:MAX_ALIAS_WORDS]
    if not words:
        return None
    if len(words) == 1 and len(words[0]) < 3:
        return None  # «ОШ» и подобное найдётся где угодно
    if len(words) == 1 and len(words[0]) < 6:
        return re.compile(rf"(?<![a-zа-я0-9]){re.escape(words[0])}(?![a-zа-я0-9])")
    if sum(len(w) for w in words) < 6:
        return None  # слишком общее, найдётся где угодно
    parts = [re.escape(_stem(w)) + r"[a-zа-я]*" for w in words]
    return re.compile(r"(?<![a-zа-я0-9])" + r"[^a-zа-я0-9]{1,6}".join(parts))


_PROGRAM_NOISE = re.compile(r"№\s*\d+\.?|\(?\b\d{2}\.\d{2}\.\d{2}\b\)?")


def clean_program_name(name: str) -> str:
    """«№15. Программная инженерия (09.03.04)» → «Программная инженерия»."""
    return " ".join(_PROGRAM_NOISE.sub(" ", name).split())


@dataclass(frozen=True)
class RowKeys:
    """Что искать в документе для одной строки."""

    olympiad_names: tuple[str, ...]
    profile: str = ""
    program_code: str = ""
    program_name: str = ""

    def olympiad_patterns(self) -> list[re.Pattern[str]]:
        patterns = [phrase_pattern(name) for name in self.olympiad_names[:MAX_ALIASES]]
        return [p for p in patterns if p is not None]

    def detail_patterns(self) -> list[tuple[re.Pattern[str], int]]:
        """Признаки строки, кроме олимпиады, с весом: код и направление важнее профиля."""
        found: list[tuple[re.Pattern[str], int]] = []
        if self.program_code:
            code = re.escape(self.program_code)
            found.append((re.compile(rf"(?<![0-9.]){code}(?![0-9])"), 3))
        for phrase, weight in ((clean_program_name(self.program_name), 3), (self.profile, 2)):
            pattern = phrase_pattern(phrase) if phrase else None
            if pattern:
                found.append((pattern, weight))
        return found


@dataclass(frozen=True)
class Page:
    """Страница документа. label — короткая метка для модели (P1, P2…)."""

    document_url: str
    number: int
    text: str
    label: str = ""


def _first_hit(patterns: Iterable[re.Pattern[str]], text: str) -> int | None:
    hits = [m.start() for p in patterns if (m := p.search(text))]
    return min(hits) if hits else None


def score_page(keys: RowKeys, text: str) -> int:
    """0 — олимпиада на странице не упомянута; больше — страница лучше подходит строке."""
    low = _lower(text)
    if _first_hit(keys.olympiad_patterns(), low) is None:
        return 0
    return 3 + sum(weight for pattern, weight in keys.detail_patterns() if pattern.search(low))


MAX_WINDOWS = 200


def excerpt(keys: RowKeys, text: str, limit: int) -> str:
    """Текст страницы для модели. Длинную страницу (большие таблицы, списки на сайте) режем
    вокруг того упоминания олимпиады, рядом с которым больше признаков строки: кода,
    направления и профиля. При равенстве — вокруг первого."""
    if len(text) <= limit:
        return text
    low = _lower(text)
    # _lower склеивает переносы и может сдвинуть позиции на несколько символов — для окна
    # в тысячи символов это не важно
    hits = sorted(m.start() for p in keys.olympiad_patterns() for m in p.finditer(low))
    details = [(m.start(), weight) for p, weight in keys.detail_patterns() for m in p.finditer(low)]

    def window(hit: int) -> int:
        return max(0, min(hit - limit // 3, len(text) - limit))

    def score(start: int) -> int:
        return sum(w for pos, w in details if start <= pos < start + limit)

    starts = [window(h) for h in hits[:MAX_WINDOWS]] or [0]
    best = max(starts, key=lambda start: (score(start), -start))
    return text[best : best + limit]


def select_pages(
    keys: RowKeys,
    pages: Sequence[Page],
    limit: int = MAX_PAGES,
    max_chars: int = MAX_PROMPT_CHARS,
) -> list[Page]:
    """До limit лучших страниц с упоминанием олимпиады, с метками P1…; пусто — не упомянута."""
    scored = [(score_page(keys, p.text), i, p) for i, p in enumerate(pages)]
    best = sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], s[1]))[:limit]
    per_page = max_chars // max(len(best), 1)
    return [
        Page(p.document_url, p.number, excerpt(keys, p.text, per_page), f"P{n}")
        for n, (_, _, p) in enumerate(best, start=1)
    ]


class AnswerError(ValueError):
    """Ответ модели не по схеме."""


@dataclass(frozen=True)
class Mismatch:
    field: str
    document: str


@dataclass(frozen=True)
class Answer:
    verdict: str
    page: str | None
    quote: str
    mismatches: tuple[Mismatch, ...]
    comment: str


def _json_object(text: str) -> Any:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise AnswerError("в ответе нет JSON-объекта")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AnswerError(f"JSON не разбирается: {exc.msg}") from None


def _text(value: Any, name: str, limit: int | None = None) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise AnswerError(f"поле {name} должно быть строкой")
    return value.strip()[:limit] if limit else value.strip()


def parse_answer(text: str) -> Answer:
    """Строгий разбор ответа модели; ошибка — AnswerError с понятной причиной."""
    data = _json_object(text)
    if not isinstance(data, dict):
        raise AnswerError("ответ должен быть объектом")
    verdict = data.get("verdict")
    if verdict not in MODEL_VERDICTS:
        raise AnswerError(f"verdict должен быть одним из {', '.join(MODEL_VERDICTS)}")
    page = data.get("page")
    if page is not None and not isinstance(page, str):
        raise AnswerError("page должна быть меткой страницы, например P1")
    raw = data.get("mismatches") or []
    if not isinstance(raw, list):
        raise AnswerError("mismatches должен быть списком")
    mismatches = []
    for item in raw:
        if not isinstance(item, dict) or item.get("field") not in FIELDS:
            raise AnswerError(f"в mismatches поле field должно быть одним из {', '.join(FIELDS)}")
        mismatches.append(Mismatch(item["field"], _text(item.get("document"), "document", 300)))
    return Answer(
        verdict=verdict,
        page=page.strip().upper() if page else None,
        quote=_text(data.get("quote"), "quote", 2000),
        mismatches=tuple(mismatches),
        comment=_text(data.get("comment"), "comment", MAX_COMMENT_CHARS),
    )


@dataclass(frozen=True)
class Verdict:
    status: str
    page: Page | None = None
    quote: str = ""
    mismatches: tuple[Mismatch, ...] = field(default_factory=tuple)
    comment: str = ""


MIN_CONDITIONS_CHARS = 10


def _quote_problem(keys: RowKeys, quote: str) -> str:
    """Почему цитата не доказывает строку: нет олимпиады или, кроме названия, нет условий."""
    low = _lower(quote)
    patterns = keys.olympiad_patterns()
    if _first_hit(patterns, low) is None:
        return "в цитате нет олимпиады строки"
    for pattern in patterns:
        low = pattern.sub(" ", low)
    if len(normalize(low)) < MIN_CONDITIONS_CHARS:
        return "в цитате только название олимпиады, без условий"
    return ""


def reconcile(answer: Answer, pages: Sequence[Page], keys: RowKeys | None = None) -> Verdict:
    """Итоговый статус: вердикт модели засчитывается, только если код нашёл цитату на странице,
    а с keys — ещё и если цитата упоминает олимпиаду строки. Дословная, но посторонняя цитата
    (заголовок документа, название олимпиады без условий) ничего не доказывает."""
    if answer.verdict == NOT_FOUND:
        return Verdict(NOT_FOUND, comment=answer.comment)
    page = next((p for p in pages if p.label == answer.page), None)
    if page is None:
        return Verdict(UNVERIFIED, comment=f"модель указала страницу {answer.page or '—'}, её нет")
    if not quote_on_page(answer.quote, page.text):
        return Verdict(
            UNVERIFIED,
            page=page,
            quote=answer.quote,
            comment="цитата не найдена на странице дословно",
        )
    if keys is not None:
        problem = _quote_problem(keys, answer.quote)
        if problem:
            return Verdict(UNVERIFIED, page=page, quote=answer.quote, comment=problem)
    status = CONTRADICTED if answer.verdict == CONTRADICTED or answer.mismatches else CONFIRMED
    return Verdict(status, page, answer.quote, answer.mismatches, answer.comment)
