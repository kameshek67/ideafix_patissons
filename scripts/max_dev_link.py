"""Ссылка, которая открывает сайт как мини-приложение MAX — без телефона и без MAX.

MAX передаёт мини-приложению подписанные данные запуска во фрагменте адреса (#WebAppData=…).
Скрипт подписывает такие данные тем же токеном бота, что и у API, — сайт в обычном браузере
подключает MAX Bridge, а API узнаёт «пользователя MAX» и хранит его дипломы.

    uv run python scripts/max_dev_link.py                          # http://localhost:3000
    uv run python scripts/max_dev_link.py --site http://localhost:8080 --start diplomas

Токен берётся из OLYMP_MAX_BOT_TOKEN (как у API). Для проверки подойдёт любой, например
OLYMP_MAX_BOT_TOKEN=local-test-token у API и здесь; настоящий токен бота сюда не нужен.
"""

import argparse
import json
import os
import sys
import time
from urllib.parse import quote, urlencode

from olymp_api.max_auth import sign


def launch_url(site: str, token: str, user_id: int, name: str, start: str | None) -> str:
    params = {
        "auth_date": str(int(time.time())),
        "chat": json.dumps({"id": user_id, "type": "DIALOG"}),
        "query_id": f"dev-{user_id}-{int(time.time())}",
        "user": json.dumps(
            {
                "id": user_id,
                "first_name": name,
                "last_name": "",
                "username": None,
                "language_code": "ru",
                "photo_url": None,
            },
            ensure_ascii=False,
        ),
    }
    if start:
        params["start_param"] = start
    params["hash"] = sign(params, token)
    fragment = urlencode(
        {
            "WebAppData": urlencode(params, quote_via=quote),
            "WebAppPlatform": "android",
            "WebAppVersion": "26.2.8",
        },
        quote_via=quote,
    )
    # параметр в адресе нужен, чтобы браузер загрузил страницу заново, а не только сменил #
    return f"{site.rstrip('/')}/?max=dev#{fragment}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--site", default="http://localhost:3000", help="адрес сайта")
    parser.add_argument("--user", type=int, default=1000001, help="id пользователя MAX")
    parser.add_argument("--name", default="Тест", help="имя пользователя")
    parser.add_argument("--start", default=None, help="startapp: diplomas, olympiad-5, program-12")
    args = parser.parse_args()
    token = os.environ.get("OLYMP_MAX_BOT_TOKEN", "")
    if not token:
        print("Задайте OLYMP_MAX_BOT_TOKEN — тот же, что у API", file=sys.stderr)
        return 1
    print(launch_url(args.site, token, args.user, args.name, args.start))
    return 0


if __name__ == "__main__":
    sys.exit(main())
