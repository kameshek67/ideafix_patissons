import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from olymp_domain.olympiad_cards import CardError, load_cards, parse_cards

DATA = Path(__file__).resolve().parents[3] / "data" / "olympiad_cards.json"

CARD: dict[str, Any] = {
    "olympiad": "Олимпиада",
    "site_url": "https://example.org",
    "summary": "Описание",
    "grades": "9–11",
    "format": ["задачи", "проект"],
    "stages": ["отборочный этап"],
    "source_url": "https://example.org/about",
    "checked": "2026-11-08",
    "tracks": [
        {
            "name": "Мобильные приложения",
            "profile": "инженерные науки",
            "topics": ["Android"],
            "source_url": "https://example.org/tracks",
            "checked": "2026-11-08",
        }
    ],
}


def dump(*cards: dict[str, Any]) -> str:
    return json.dumps({"olympiads": list(cards)}, ensure_ascii=False)


def test_real_file_is_valid_and_sourced() -> None:
    cards = load_cards(DATA)
    assert cards
    for card in cards:
        assert card.source_url.startswith("https://")
        assert all(t.source_url.startswith("https://") for t in card.tracks)


def test_parses_card_with_track() -> None:
    (card,) = parse_cards(dump(CARD))
    assert card.formats == ("задачи", "проект")
    assert card.tracks[0].topics == ("Android",)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda c: c.pop("site_url"), "site_url"),
        (lambda c: c.update(site_url="http://example.org"), "https://"),
        (lambda c: c.update(format=["викторина"]), "неизвестный формат"),
        (lambda c: c.update(checked="вчера"), "ГГГГ-ММ-ДД"),
        (lambda c: c["tracks"][0].pop("source_url"), "source_url"),
        (lambda c: c["tracks"][0].pop("profile"), "profile"),
        (lambda c: c["tracks"].append(deepcopy(c["tracks"][0])), "повторяются"),
    ],
)
def test_rejects_bad_card(change: Any, message: str) -> None:
    card = deepcopy(CARD)
    change(card)
    with pytest.raises(CardError, match=message):
        parse_cards(dump(card))


def test_rejects_duplicate_card_and_bad_json() -> None:
    with pytest.raises(CardError, match="повторяется"):
        parse_cards(dump(CARD, CARD))
    with pytest.raises(CardError, match="не JSON"):
        parse_cards("{")
    with pytest.raises(CardError, match="olympiads"):
        parse_cards("[]")
