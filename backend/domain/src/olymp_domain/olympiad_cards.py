"""Карточки олимпиад из data/olympiad_cards.json: формат и проверка без БД.

Карточку пишет и проверяет человек в PR по официальному сайту олимпиады. Ошибка формата
останавливает сборку базы с указанием карточки и поля, а не теряет данные молча.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

FORMATS = ("задачи", "проект", "защита", "командная", "тезисы")


class CardError(ValueError):
    """В файле карточек ошибка: текст сообщения говорит, где именно."""


@dataclass(frozen=True)
class Track:
    name: str
    profile: str
    topics: tuple[str, ...]
    source_url: str
    checked: date


@dataclass(frozen=True)
class Card:
    olympiad: str  # canonical_name из таблицы olympiads
    site_url: str
    summary: str
    grades: str
    formats: tuple[str, ...]
    stages: tuple[str, ...]
    source_url: str
    checked: date
    tracks: tuple[Track, ...] = field(default_factory=tuple)


def _text(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CardError(f"{where}: нужно непустое поле «{key}»")
    return value.strip()


def _url(data: dict[str, Any], key: str, where: str) -> str:
    value = _text(data, key, where)
    if not value.startswith("https://"):
        raise CardError(f"{where}: «{key}» должен быть адресом https://, а не «{value}»")
    return value


def _texts(data: dict[str, Any], key: str, where: str, *, required: bool) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
        raise CardError(f"{where}: «{key}» — список непустых строк")
    if required and not value:
        raise CardError(f"{where}: «{key}» не должен быть пустым")
    return tuple(x.strip() for x in value)


def _checked(data: dict[str, Any], where: str) -> date:
    raw = _text(data, "checked", where)
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise CardError(f"{where}: «checked» — дата ГГГГ-ММ-ДД, а не «{raw}»") from None


def _track(data: Any, where: str) -> Track:
    if not isinstance(data, dict):
        raise CardError(f"{where}: трек должен быть объектом")
    return Track(
        name=_text(data, "name", where),
        profile=_text(data, "profile", where),
        topics=_texts(data, "topics", where, required=False),
        source_url=_url(data, "source_url", where),
        checked=_checked(data, where),
    )


def parse_card(data: Any, index: int) -> Card:
    where = f"карточка №{index}"
    if not isinstance(data, dict):
        raise CardError(f"{where}: карточка должна быть объектом")
    olympiad = _text(data, "olympiad", where)
    where = f"карточка «{olympiad}»"
    formats = _texts(data, "format", where, required=False)
    unknown = [f for f in formats if f not in FORMATS]
    if unknown:
        raise CardError(f"{where}: неизвестный формат {unknown}, допустимо {list(FORMATS)}")
    tracks = [_track(t, f"{where}, трек №{i}") for i, t in enumerate(data.get("tracks", []), 1)]
    names = [t.name.lower() for t in tracks]
    if len(set(names)) != len(names):
        raise CardError(f"{where}: названия треков повторяются")
    return Card(
        olympiad=olympiad,
        site_url=_url(data, "site_url", where),
        summary=_text(data, "summary", where),
        grades=_text(data, "grades", where),
        formats=formats,
        stages=_texts(data, "stages", where, required=False),
        source_url=_url(data, "source_url", where),
        checked=_checked(data, where),
        tracks=tuple(tracks),
    )


def parse_cards(text: str) -> list[Card]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CardError(f"файл карточек не JSON: {exc}") from None
    items = raw.get("olympiads") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise CardError("в корне файла нужен список «olympiads»")
    cards = [parse_card(item, i) for i, item in enumerate(items, 1)]
    seen = [c.olympiad for c in cards]
    for name in seen:
        if seen.count(name) > 1:
            raise CardError(f"карточка «{name}» повторяется")
    return cards


def load_cards(path: Path) -> list[Card]:
    return parse_cards(path.read_text(encoding="utf-8"))
