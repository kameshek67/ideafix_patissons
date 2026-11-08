"""Справочник общих правил приёма из data/admission_rules.json (инструмент помощника).

Что такое БВИ, сколько действует диплом, сколько вузов можно выбрать — это не данные вузов, а
общие нормы (273-ФЗ, Порядок приёма, Порядок проведения олимпиад). Модель не должна отвечать
на такие вопросы из памяти: она берёт пункт справочника вместе с источником и цитатой.

Пункт пишет и проверяет человек по открытой странице источника; у каждого пункта есть дословная
цитата и дата проверки. Ошибка формата останавливает загрузку с указанием пункта и поля.
"""

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from .interests import STOP_WORDS, word_matches

RULES_FILE = "admission_rules.json"
MAX_QUOTE_LEN = 300
# слова, по которым одним правило не находят: «диплом», «олимпиада», «вуз» есть почти везде
GENERIC_STEMS = ("олимпиад", "диплом", "школьн", "поступ", "вуз", "правил", "прием")
# короткие слова, которые всё же несут смысл («ИД» — индивидуальные достижения)
SHORT_WORDS = frozenset({"ид"})
RE_TOKEN = re.compile(r"[^\W_]+")


class RuleError(ValueError):
    """В справочнике правил ошибка: текст сообщения говорит, где именно."""


@dataclass(frozen=True)
class Rule:
    id: str
    topic: str
    keywords: tuple[str, ...]
    text: str
    source_title: str
    source_url: str
    quote: str
    checked: date


def _text(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuleError(f"{where}: нужно непустое поле «{key}»")
    return value.strip()


def parse_rule(data: Any, index: int) -> Rule:
    where = f"пункт №{index}"
    if not isinstance(data, dict):
        raise RuleError(f"{where}: пункт должен быть объектом")
    rule_id = _text(data, "id", where)
    where = f"пункт «{rule_id}»"
    keywords = data.get("keywords")
    if (
        not isinstance(keywords, list)
        or not keywords
        or not all(isinstance(k, str) and k.strip() for k in keywords)
    ):
        raise RuleError(f"{where}: «keywords» — непустой список непустых строк")
    url = _text(data, "source_url", where)
    if not url.startswith(("https://", "http://publication.pravo.gov.ru/")):
        raise RuleError(f"{where}: «source_url» должен быть адресом https://, а не «{url}»")
    quote = _text(data, "quote", where)
    if len(quote) > MAX_QUOTE_LEN:
        raise RuleError(f"{where}: «quote» длиннее {MAX_QUOTE_LEN} символов ({len(quote)})")
    raw_date = _text(data, "checked", where)
    try:
        checked = date.fromisoformat(raw_date)
    except ValueError:
        raise RuleError(f"{where}: «checked» — дата ГГГГ-ММ-ДД, а не «{raw_date}»") from None
    return Rule(
        id=rule_id,
        topic=_text(data, "topic", where),
        keywords=tuple(k.strip() for k in keywords),
        text=_text(data, "text", where),
        source_title=_text(data, "source_title", where),
        source_url=url,
        quote=quote,
        checked=checked,
    )


def parse_rules(text: str) -> list[Rule]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuleError(f"файл правил не JSON: {exc}") from None
    items = raw.get("rules") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not items:
        raise RuleError("в корне файла нужен непустой список «rules»")
    rules = [parse_rule(item, i) for i, item in enumerate(items, 1)]
    ids = [r.id for r in rules]
    for rule_id in ids:
        if ids.count(rule_id) > 1:
            raise RuleError(f"пункт «{rule_id}» повторяется")
    return rules


def load_rules(path: Path) -> list[Rule]:
    return parse_rules(path.read_text(encoding="utf-8"))


def default_path() -> Path:
    """data/admission_rules.json: рядом с кодом репозитория или в OLYMP_DATA_DIR."""
    data_dir = os.environ.get("OLYMP_DATA_DIR")
    base = Path(data_dir) if data_dir else Path(__file__).resolve().parents[4] / "data"
    return base / RULES_FILE


@lru_cache(maxsize=1)
def default_rules() -> tuple[Rule, ...]:
    return tuple(load_rules(default_path()))


def _words(text: str) -> list[str]:
    """Слова вопроса или ключа: буквенные длиннее двух букв, числа («100», «75»), «ид»; ё → е."""
    tokens = RE_TOKEN.findall(text.lower().replace("ё", "е"))
    return [
        t for t in tokens if (len(t) > 2 or t.isdigit() or t in SHORT_WORDS) and t not in STOP_WORDS
    ]


def _weight(word: str) -> int:
    return 0 if word.startswith(GENERIC_STEMS) else 1


def _phrase_score(phrase: str, query_words: list[str]) -> int:
    """Вес фразы-ключа, если каждое её слово нашлось в вопросе (по основе); иначе 0."""
    words = _words(phrase)
    if not words or not all(any(word_matches(q, w) for q in query_words) for w in words):
        return 0
    return sum(_weight(w) for w in words)


def score_rule(rule: Rule, query_words: list[str]) -> int:
    scores = [_phrase_score(k, query_words) for k in (*rule.keywords, rule.topic)]
    # самая длинная совпавшая фраза важнее россыпи коротких; несколько фраз — небольшой бонус
    return max(scores) * 10 + sum(1 for s in scores if s)


def find_rules(query: str, limit: int = 3, rules: tuple[Rule, ...] | None = None) -> list[Rule]:
    """Пункты справочника, подходящие к вопросу, лучшие первыми.

    Ключ-фраза подходит, если каждое её слово есть в вопросе (по основе слова, в любом порядке
    и с любыми окончаниями). Фраза из одних общих слов («диплом», «олимпиада») не подходит.
    """
    query_words = _words(query)
    if not query_words or limit <= 0:
        return []
    pool = default_rules() if rules is None else rules
    scored = [(score_rule(rule, query_words), pos, rule) for pos, rule in enumerate(pool)]
    # score >= 10 — нашлась хотя бы одна фраза с негенеричным словом
    found = sorted((s for s in scored if s[0] >= 10), key=lambda s: (-s[0], s[1]))
    return [rule for _, _, rule in found[:limit]]
