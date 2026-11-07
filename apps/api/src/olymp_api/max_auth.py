"""Вход из мини-приложения MAX: проверка подписи данных запуска (initData).

MAX передаёт мини-приложению строку initData, подписанную токеном бота. Сайт пересылает
её в заголовке ``X-Max-Init-Data``, а API проверяет подпись по алгоритму из документации
MAX (https://dev.max.ru/docs/webapps/validation):

1. строку разбирают на пары key=value и URL-декодируют значения;
2. пару ``hash`` откладывают, остальные сортируют по ключу и склеивают через ``\\n``;
3. ключ подписи — HMAC-SHA256 токена бота с ключом ``WebAppData``;
4. подпись — HMAC-SHA256 склеенной строки этим ключом, в hex; она должна совпасть с ``hash``.

Токен бота знает только сервер, поэтому подделать пользователя на клиенте нельзя.
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request

HEADER = "X-Max-Init-Data"
# часы клиента и сервера могут немного расходиться
CLOCK_SKEW = 300


class InitDataError(ValueError):
    """Данные запуска не прошли проверку."""


@dataclass(frozen=True)
class MaxUser:
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    language_code: str = ""
    photo_url: str = ""


def sign(params: dict[str, str], bot_token: str) -> str:
    """Подпись данных запуска так, как её считает MAX."""
    launch_params = "\n".join(f"{key}={value}" for key, value in sorted(params.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, launch_params.encode(), hashlib.sha256).hexdigest()


def validate_init_data(
    init_data: str, bot_token: str, max_age: int, now: float | None = None
) -> MaxUser:
    """Проверяет подпись и срок годности initData, возвращает пользователя MAX."""
    pairs = parse_qsl(init_data, keep_blank_values=True)
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise InitDataError("параметры повторяются")
    params = dict(pairs)
    received = params.pop("hash", "")
    if not received:
        raise InitDataError("нет подписи")
    if not hmac.compare_digest(sign(params, bot_token), received):
        raise InitDataError("подпись не совпала")

    try:
        auth_date = int(params.get("auth_date", ""))
    except ValueError:
        raise InitDataError("нет времени запуска") from None
    age = (time.time() if now is None else now) - auth_date
    if max_age and (age > max_age or age < -CLOCK_SKEW):
        raise InitDataError("данные запуска устарели — откройте мини-приложение заново")

    try:
        user = json.loads(params.get("user", ""))
    except ValueError:
        raise InitDataError("нет пользователя") from None
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise InitDataError("нет пользователя")
    return MaxUser(
        id=user["id"],
        **{
            field: str(user.get(field) or "")[:500]
            for field in ("first_name", "last_name", "username", "language_code", "photo_url")
        },
    )


async def max_user(request: Request) -> MaxUser:
    """Зависимость FastAPI: пользователь MAX из заголовка запроса."""
    settings = request.app.state.settings
    if not settings.max_bot_token:
        raise HTTPException(503, "Вход через MAX не настроен: задайте OLYMP_MAX_BOT_TOKEN")
    init_data = request.headers.get(HEADER, "")
    if not init_data:
        raise HTTPException(401, f"Нужны данные запуска MAX (заголовок {HEADER})")
    try:
        return validate_init_data(init_data, settings.max_bot_token, settings.max_init_data_ttl)
    except InitDataError as exc:
        raise HTTPException(401, f"Данные запуска MAX не прошли проверку: {exc}") from None
