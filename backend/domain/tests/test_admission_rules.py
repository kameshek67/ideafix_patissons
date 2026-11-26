import json
from pathlib import Path
from typing import Any

import pytest
from olymp_domain.admission_rules import (
    MAX_QUOTE_LEN,
    RuleError,
    default_path,
    find_rules,
    load_rules,
    parse_rules,
)

DATA = Path(__file__).resolve().parents[3] / "data" / "admission_rules.json"

RULE: dict[str, Any] = {
    "id": "term",
    "topic": "срок действия диплома",
    "keywords": ["срок действия диплома"],
    "text": "Четыре года.",
    "source_title": "Закон",
    "source_url": "https://example.org/law",
    "quote": "в течение четырех лет",
    "checked": "2026-11-08",
}


def dump(*rules: dict[str, Any]) -> str:
    return json.dumps({"rules": list(rules)}, ensure_ascii=False)


def ids(query: str, limit: int = 3) -> list[str]:
    return [r.id for r in find_rules(query, limit)]


def test_real_file_is_valid_and_sourced() -> None:
    rules = load_rules(DATA)
    assert 15 <= len(rules) <= 25
    assert default_path() == DATA
    for rule in rules:
        assert rule.source_url.startswith(("https://", "http://publication.pravo.gov.ru/"))
        assert 0 < len(rule.quote) <= MAX_QUOTE_LEN
        assert rule.checked.year >= 2026


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("сколько действует диплом", "diploma-term"),
        ("Срок действия диплома олимпиады?", "diploma-term"),
        ("что такое бви", "bvi"),
        ("Что такое БВИ?", "bvi"),
        ("что значит 100 баллов", "hundred"),
        ("какой балл егэ нужен для подтверждения", "ege-confirm"),
        ("можно ли использовать бви в нескольких вузах", "bvi-one-program"),
        ("сколько вузов можно выбрать", "limits-5"),
        ("чем всош отличается от перечня", "vsosh-vs-perechen"),
        ("за ид сколько баллов", "individual-achievements"),
        ("что изменится в 2027", "rules-2027"),
    ],
)
def test_question_finds_its_rule_first(query: str, expected: str) -> None:
    assert ids(query)[0] == expected


def test_limit_and_garbage() -> None:
    assert len(find_rules("бви 100 баллов диплом", limit=2)) <= 2
    assert find_rules("сколько действует диплом", limit=0) == []
    assert find_rules("рецепт борща с говядиной") == []
    assert find_rules("") == []
    # общие слова сами по себе правило не находят
    assert find_rules("диплом олимпиада") == []


def test_parse_ok_and_search_over_given_rules() -> None:
    rules = tuple(parse_rules(dump(RULE)))
    assert [r.id for r in find_rules("срок действия диплома", rules=rules)] == ["term"]


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"source_url": "http://example.org"}, "https://"),
        ({"quote": ""}, "quote"),
        ({"quote": "я" * (MAX_QUOTE_LEN + 1)}, "длиннее"),
        ({"keywords": []}, "keywords"),
        ({"text": " "}, "text"),
        ({"checked": "вчера"}, "checked"),
    ],
)
def test_invalid_rule_is_reported_with_its_id(patch: dict[str, Any], message: str) -> None:
    with pytest.raises(RuleError, match=message) as exc:
        parse_rules(dump({**RULE, **patch}))
    assert "«term»" in str(exc.value)


def test_duplicate_ids_and_bad_file() -> None:
    with pytest.raises(RuleError, match="повторяется"):
        parse_rules(dump(RULE, RULE))
    with pytest.raises(RuleError, match="не JSON"):
        parse_rules("{")
    with pytest.raises(RuleError, match="rules"):
        parse_rules("{}")
