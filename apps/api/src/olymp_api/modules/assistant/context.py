"""Контекст диалога (C1): id найденного и короткая сводка фактов между репликами.

Сервер отдаёт контекст в событии done, клиент хранит его и присылает со следующим сообщением.
Подделать его нельзя: контекст подписан HMAC-SHA256 серверным ключом, неверная подпись — контекст
молча не принимается. Внутри только id и названия из базы, без слов ученика.

Формат: `<base64url(JSON)>.<base64url(HMAC)>`, JSON —
`{"v": 1, "o": [id олимпиад], "p": [[id профиля, id олимпиады]], "g": [id направлений],
"u": [id вузов], "n": ["сводка ответа", …], "a": [отпечаток ответа, …]}`.

Отпечатки — sha256 последних проверенных ответов: если клиент прислал прошлый ответ без
изменений, его текст считается фактом для проверки (V2) — уточнение может повторить то, что
помощник уже сказал по данным.
"""

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass, field
from typing import Any

from .tools import ToolContext

VERSION = 1
MAX_IDS = 30  # последних id каждого вида
MAX_NOTES = 3  # сводок последних ответов
MAX_NOTE_CHARS = 400
MAX_NOTE_ITEMS = 8
MAX_ANSWERS = 3
MAX_TOKEN_CHARS = 8000
# без настройки — случайный ключ на процесс: после рестарта старые контексты просто не принимаются
_PROCESS_KEY = secrets.token_bytes(32)
_ID_MARK = re.compile(r"\s*\[[a-z_]+=\d+\]")
_KIND_TITLE = {"olympiad": "олимпиады", "program": "направления", "university": "вузы"}


@dataclass
class DialogContext:
    olympiads: list[int] = field(default_factory=list)
    profiles: list[tuple[int, int]] = field(default_factory=list)  # (профиль, его олимпиада)
    programs: list[int] = field(default_factory=list)
    universities: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)  # отпечатки проверенных ответов

    def seed(self, ctx: ToolContext) -> None:
        """id прошлых ответов становятся «найденными» и в этом ответе."""
        ctx.olympiads.update(self.olympiads)
        ctx.olympiads.update(olympiad for _, olympiad in self.profiles)
        ctx.profiles.update(dict(self.profiles))
        ctx.programs.update(self.programs)
        ctx.universities.update(self.universities)

    def fact_lines(self) -> list[str]:
        """Сводка для проверки фактов: без пометок id, иначе id оправдывал бы любое число."""
        return [_ID_MARK.sub("", note) for note in self.notes]

    def verified(self, text: str) -> bool:
        """Этот текст — ответ, который сервер сам проверил и отдал в прошлых репликах."""
        return digest(text) in self.answers


def digest(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()[:24]


def context_key(secret: str | None) -> bytes:
    return secret.encode() if secret else _PROCESS_KEY


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str, key: bytes) -> str:
    return _b64(hmac.new(key, body.encode(), hashlib.sha256).digest())


def encode(dialog: DialogContext, key: bytes) -> str:
    payload = {
        "v": VERSION,
        "o": dialog.olympiads,
        "p": [list(pair) for pair in dialog.profiles],
        "g": dialog.programs,
        "u": dialog.universities,
        "n": dialog.notes,
        "a": dialog.answers,
    }
    body = _b64(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    return f"{body}.{_sign(body, key)}"


def _ids(value: Any) -> list[int]:
    if not isinstance(value, list):
        raise ValueError("ожидался список id")
    out = [v for v in value if isinstance(v, int) and not isinstance(v, bool)]
    if len(out) != len(value):
        raise ValueError("id должны быть числами")
    return out[-MAX_IDS:]


def decode(token: str | None, key: bytes) -> DialogContext | None:
    """Контекст из запроса или None, если его нет, подпись неверна или формат чужой."""
    if not token or len(token) > MAX_TOKEN_CHARS or token.count(".") != 1:
        return None
    body, signature = token.split(".")
    if not hmac.compare_digest(signature.encode(), _sign(body, key).encode()):
        return None
    try:
        data = json.loads(_unb64(body))
        if not isinstance(data, dict) or data.get("v") != VERSION:
            return None
        pairs = data.get("p", [])
        if not isinstance(pairs, list):
            return None
        profiles = [tuple(_ids(pair)) for pair in pairs]
        notes, answers = data.get("n", []), data.get("a", [])
        if any(len(pair) != 2 for pair in profiles) or not isinstance(notes, list):
            return None
        if not isinstance(answers, list):
            return None
        return DialogContext(
            olympiads=_ids(data.get("o", [])),
            profiles=[(a, b) for a, b in profiles][-MAX_IDS:],
            programs=_ids(data.get("g", [])),
            universities=_ids(data.get("u", [])),
            notes=[str(n)[:MAX_NOTE_CHARS] for n in notes][-MAX_NOTES:],
            answers=[str(a)[:64] for a in answers][-MAX_ANSWERS:],
        )
    except (ValueError, TypeError, binascii.Error):
        return None


def _merge[T: (int, tuple[int, int])](previous: list[T], found: set[T]) -> list[T]:
    """Старые id в прежнем порядке, новые — в конце; остаются последние MAX_IDS."""
    merged = list(previous)
    merged.extend(sorted(found.difference(previous)))
    return merged[-MAX_IDS:]


def note_line(entities: list[dict[str, Any]]) -> str:
    """Одна строка «что найдено» по карточкам ответа: названия из базы и их id."""
    groups: dict[str, list[str]] = {}
    for item in entities[:MAX_NOTE_ITEMS]:
        kind = str(item.get("kind"))
        label = str(item.get("label") or "").strip()
        if kind not in _KIND_TITLE or not label:
            continue
        hint = str(item.get("hint") or "").strip()
        text = f"{label} — {hint}" if kind == "program" and hint else label
        groups.setdefault(kind, []).append(f"{text} [{kind}_id={item.get('id')}]")
    line = "; ".join(f"{_KIND_TITLE[kind]}: {', '.join(items)}" for kind, items in groups.items())
    if len(line) > MAX_NOTE_CHARS:
        line = line[:MAX_NOTE_CHARS].rsplit(",", 1)[0]
    return line


def advance(
    previous: DialogContext | None,
    ctx: ToolContext,
    entities: list[dict[str, Any]],
    answer: str = "",
) -> DialogContext:
    """Контекст после ответа: накопленные id, сводка и отпечаток этого ответа к прошлым."""
    old = previous or DialogContext()
    note = note_line(entities)
    return DialogContext(
        olympiads=_merge(old.olympiads, ctx.olympiads),
        profiles=_merge(old.profiles, set(ctx.profiles.items())),
        programs=_merge(old.programs, ctx.programs),
        universities=_merge(old.universities, ctx.universities),
        notes=[*old.notes, note][-MAX_NOTES:] if note else old.notes,
        answers=[*old.answers, digest(answer)][-MAX_ANSWERS:] if answer else old.answers,
    )
