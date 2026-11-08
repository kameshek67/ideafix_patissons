"""Бот мини-приложения «Олимп» в MAX.

    olymp-max-bot check   — проверить токен: имя бота и ссылки на мини-приложение
    olymp-max-bot run     — отвечать в личке: приветствие с кнопками мини-приложения и сайта

Мини-приложению бот не нужен: кнопка запуска появляется в чате с ботом, как только в его
настройках на business.max.ru указан адрес сайта. Этот процесс только отвечает на первое
сообщение, чтобы ученик сразу понял, что делать. Обновления — через long polling
(GET /updates); для большой нагрузки MAX советует вебхуки.

Переменные: OLYMP_MAX_BOT_TOKEN — токен бота; OLYMP_MAX_CA_DIR — каталог с сертификатом
Минцифры, которым подписан platform-api2.max.ru (см. infra/certs/README.md); OLYMP_SITE_URL —
адрес сайта для кнопки «Сайт» (по умолчанию стенд https://ideafix.patissons.tech).
"""

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

API_URL = "https://platform-api2.max.ru"
SITE_URL = "https://ideafix.patissons.tech"
UPDATE_TYPES = "bot_started,message_created"

# (method, path, query, body) -> JSON-ответ
Call = Callable[[str, str, dict[str, Any] | None, dict[str, Any] | None], Any]


class MaxApiError(RuntimeError):
    """Ошибка запроса к API бота MAX."""


def ssl_context(ca_dir: str | None) -> ssl.SSLContext:
    """Системные сертификаты плюс сертификаты из ca_dir (корневой сертификат Минцифры)."""
    context = ssl.create_default_context()
    if ca_dir and Path(ca_dir).is_dir():
        for path in sorted(Path(ca_dir).iterdir()):
            if path.suffix.lower() in {".pem", ".crt", ".cer"}:
                context.load_verify_locations(cafile=str(path))
    return context


def http_call(token: str, base: str = API_URL, ca_dir: str | None = None) -> Call:
    context = ssl_context(ca_dir)

    def call(
        method: str, path: str, query: dict[str, Any] | None, body: dict[str, Any] | None
    ) -> Any:
        url = base + path + (f"?{urllib.parse.urlencode(query)}" if query else "")
        request = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
            method=method,
            headers={"Authorization": token, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=45, context=context) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            raise MaxApiError(f"HTTP {exc.code}: {detail}") from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLCertVerificationError):
                raise MaxApiError(
                    "сертификат platform-api2.max.ru не проверен: положите корневой сертификат "
                    "Минцифры в каталог OLYMP_MAX_CA_DIR (см. infra/certs/README.md)"
                ) from None
            raise MaxApiError(str(exc.reason)) from None
        except TimeoutError:
            raise MaxApiError("MAX не ответил вовремя") from None

    return call


# ---------------------------------------------------------------- сообщения


def open_app_button(text: str, bot: str, payload: str | None = None) -> dict[str, Any]:
    button: dict[str, Any] = {"type": "open_app", "text": text, "web_app": bot}
    if payload:
        button["payload"] = payload
    return button


def link_button(text: str, url: str) -> dict[str, Any]:
    return {"type": "link", "text": text, "url": url}


def keyboard(bot: str, site: str) -> dict[str, Any]:
    """Кнопки под сообщением: мини-приложение, сразу «Дипломы» и сайт в браузере."""
    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [open_app_button("Открыть «Олимп»", bot)],
                [open_app_button("Мои дипломы", bot, "diplomas")],
                [link_button("Сайт «Олимпа»", site)],
            ]
        },
    }


def welcome(bot: str, first_name: str = "", site: str = SITE_URL) -> dict[str, Any]:
    """Первое сообщение: что умеет мини-приложение, и кнопки запуска."""
    hello = f"Привет, {first_name}!" if first_name else "Привет!"
    return {
        "text": (
            f"{hello} «Олимп» показывает, в каких вузах олимпиады дают БВИ "
            "и 100 баллов по правилам приёма 2026 года.\n\n"
            "Добавь свои дипломы во вкладке «Дипломы» — увидишь все вузы и направления, "
            "где они дают льготы, с учётом степени диплома, класса и года. "
            "А ИИ-помощник подберёт олимпиады под твои увлечения.\n\n"
            f"Удобнее с компьютера — открой сайт: {site}"
        ),
        "attachments": [keyboard(bot, site)],
    }


def hint(bot: str, site: str = SITE_URL) -> dict[str, Any]:
    """Ответ на любое другое сообщение: бот не ведёт диалог, всё — в мини-приложении."""
    return {
        "text": (
            "Я не отвечаю на сообщения — всё происходит в мини-приложении «Олимп». "
            "Там можно найти льготы по вузу или олимпиаде, добавить дипломы "
            f"и спросить ИИ-помощника. Сайт: {site}"
        ),
        "attachments": [keyboard(bot, site)],
    }


def reply_for(
    update: dict[str, Any], bot: str, site: str = SITE_URL
) -> tuple[int, dict[str, Any]] | None:
    """Кому и что ответить на событие; None — событие без ответа."""
    kind = update.get("update_type")
    if kind == "bot_started":
        user = update.get("user") or {}
        if isinstance(user.get("user_id"), int):
            name = user.get("first_name") or user.get("name") or ""
            return user["user_id"], welcome(bot, name, site)
        return None
    if kind == "message_created":
        message = update.get("message") or {}
        sender = message.get("sender") or {}
        recipient = message.get("recipient") or {}
        text = ((message.get("body") or {}).get("text") or "").strip().lower()
        # только личные сообщения людей: в группах и от ботов молчим
        if recipient.get("chat_type") != "dialog" or sender.get("is_bot"):
            return None
        if not isinstance(sender.get("user_id"), int):
            return None
        if text in {"/start", "start", "начать", "/help", "помощь", "привет"}:
            return sender["user_id"], welcome(bot, sender.get("first_name") or "", site)
        return sender["user_id"], hint(bot, site)
    return None


# ---------------------------------------------------------------- команды


def bot_name(me: dict[str, Any]) -> str:
    name = me.get("username")
    if not name:
        raise MaxApiError("у бота нет публичного имени (username) — задайте его на business.max.ru")
    return str(name)


def check(call: Call, site: str = SITE_URL) -> str:
    me = call("GET", "/me", None, None)
    name = bot_name(me)
    return "\n".join(
        [
            f"Токен рабочий: бот «{me.get('first_name') or me.get('name') or name}» (@{name}).",
            f"Мини-приложение:   https://max.ru/{name}?startapp",
            f"Сразу «Дипломы»:   https://max.ru/{name}?startapp=diplomas",
            f"Кнопка «Сайт»:     {site}",
            f"Для .env:          OLYMP_MAX_BOT_NAME={name}",
        ]
    )


def run(
    call: Call,
    *,
    site: str = SITE_URL,
    once: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Отвечает на события, пока процесс не остановят; возвращает число отправленных ответов."""
    name = bot_name(call("GET", "/me", None, None))
    print(f"Бот @{name} слушает обновления (long polling)", flush=True)
    marker: int | None = None
    sent = 0
    delay = 1.0
    while True:
        try:
            query: dict[str, Any] = {"types": UPDATE_TYPES, "timeout": 30, "limit": 100}
            if marker is not None:
                query["marker"] = marker
            data = call("GET", "/updates", query, None) or {}
            marker = data.get("marker", marker)
            for update in data.get("updates") or []:
                reply = reply_for(update, name, site)
                if reply:
                    user_id, body = reply
                    call("POST", "/messages", {"user_id": user_id}, body)
                    sent += 1
            delay = 1.0
        except MaxApiError as exc:
            print(f"Ошибка API MAX: {exc}; повтор через {delay:.0f} с", file=sys.stderr, flush=True)
            if once:
                raise
            sleep(delay)
            delay = min(delay * 2, 60)
        if once:
            return sent


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else "check"
    token = os.environ.get("OLYMP_MAX_BOT_TOKEN", "").strip()
    if command not in {"check", "run"}:
        print(__doc__)
        return 2
    if not token:
        print("Не задан OLYMP_MAX_BOT_TOKEN — токен бота с business.max.ru", file=sys.stderr)
        return 1
    call = http_call(token, ca_dir=os.environ.get("OLYMP_MAX_CA_DIR") or None)
    site = os.environ.get("OLYMP_SITE_URL", "").strip().rstrip("/") or SITE_URL
    try:
        if command == "check":
            print(check(call, site))
        else:
            run(call, site=site)
    except MaxApiError as exc:
        print(f"Ошибка API MAX: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
