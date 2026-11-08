"""Бот мини-приложения: ответы на события и команды — на поддельном API MAX."""

from typing import Any

import pytest
from olymp_workers.max_bot import (
    SITE_URL,
    MaxApiError,
    check,
    hint,
    main,
    reply_for,
    run,
    welcome,
)

ME = {"user_id": 1, "first_name": "Олимп", "username": "olymp_bot", "is_bot": True}


class FakeApi:
    def __init__(self, updates: list[dict[str, Any]]) -> None:
        self.updates = updates
        self.calls: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]] = []

    def __call__(
        self, method: str, path: str, query: dict[str, Any] | None, body: dict[str, Any] | None
    ) -> Any:
        self.calls.append((method, path, query, body))
        if path == "/me":
            return ME
        if path == "/updates":
            return {"updates": self.updates, "marker": 42}
        return {"message": {"body": {"mid": "mid.1"}}}


def started(user_id: int = 7) -> dict[str, Any]:
    return {
        "update_type": "bot_started",
        "timestamp": 1,
        "chat_id": 100,
        "user": {"user_id": user_id, "first_name": "Маша", "username": None, "is_bot": False},
    }


def message(text: str, chat_type: str = "dialog", is_bot: bool = False) -> dict[str, Any]:
    return {
        "update_type": "message_created",
        "timestamp": 1,
        "message": {
            "sender": {"user_id": 7, "first_name": "Маша", "is_bot": is_bot},
            "recipient": {"chat_id": 100, "chat_type": chat_type, "user_id": 1},
            "body": {"mid": "mid.2", "text": text},
        },
    }


def test_welcome_has_app_and_site_buttons() -> None:
    body = welcome("olymp_bot", "Маша")
    assert body["text"].startswith("Привет, Маша!")
    assert SITE_URL in body["text"]
    keyboard = body["attachments"][0]
    assert keyboard["type"] == "inline_keyboard"
    app, diplomas, site = (row[0] for row in keyboard["payload"]["buttons"])
    assert app == {"type": "open_app", "text": "Открыть «Олимп»", "web_app": "olymp_bot"}
    assert diplomas["web_app"] == "olymp_bot" and diplomas["payload"] == "diplomas"
    assert site == {
        "type": "link",
        "text": "Сайт «Олимпа»",
        "url": "https://ideafix.patissons.tech",
    }


def test_site_url_is_configurable() -> None:
    body = welcome("olymp_bot", site="https://example.test")
    assert body["attachments"][0]["payload"]["buttons"][2][0]["url"] == "https://example.test"
    assert "https://example.test" in hint("olymp_bot", "https://example.test")["text"]


def test_replies() -> None:
    assert reply_for(started(), "olymp_bot") == (7, welcome("olymp_bot", "Маша"))
    assert reply_for(message("/start"), "olymp_bot") == (7, welcome("olymp_bot", "Маша"))
    assert reply_for(message("/help"), "olymp_bot") == (7, welcome("olymp_bot", "Маша"))
    # на обычный текст — подсказка с теми же кнопками, а не молчание
    assert reply_for(message("какие вузы?"), "olymp_bot") == (7, hint("olymp_bot"))
    # в группах и ботам бот молчит
    assert reply_for(message("/start", chat_type="chat"), "olymp_bot") is None
    assert reply_for(message("/start", is_bot=True), "olymp_bot") is None
    assert reply_for({"update_type": "bot_stopped"}, "olymp_bot") is None


def test_run_answers_updates_and_keeps_marker() -> None:
    api = FakeApi([started(7), message("привет"), message("/start")])
    assert run(api, once=True) == 3
    polls = [c for c in api.calls if c[1] == "/updates"]
    assert polls[0][2] == {"types": "bot_started,message_created", "timeout": 30, "limit": 100}
    sent = [c for c in api.calls if c[0] == "POST"]
    assert [c[2] for c in sent] == [{"user_id": 7}] * 3


def test_check_prints_links() -> None:
    out = check(FakeApi([]))
    assert "@olymp_bot" in out
    assert "https://max.ru/olymp_bot?startapp=diplomas" in out
    assert "OLYMP_MAX_BOT_NAME=olymp_bot" in out
    assert "https://ideafix.patissons.tech" in out


def test_check_requires_public_name() -> None:
    def no_name(*_: Any) -> Any:
        return {"user_id": 1, "first_name": "Бот", "username": None}

    with pytest.raises(MaxApiError):
        check(no_name)


def test_main_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLYMP_MAX_BOT_TOKEN", raising=False)
    assert main(["check"]) == 1
    assert main(["unknown"]) == 2
