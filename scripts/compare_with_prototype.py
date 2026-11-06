"""Сверка нового API с прототипом из ветки main: одинаковые ли ответы.

Прототип отдаёт API на http://localhost:8000/api (docker compose up в ветке main).
Новый API по умолчанию поднимается прямо в процессе из OLYMP_DATABASE_URL:

    uv run python scripts/compare_with_prototype.py
    uv run python scripts/compare_with_prototype.py --old http://localhost:8000/api --quick
    uv run python scripts/compare_with_prototype.py --new http://localhost:8010/v1

Сравниваются все направления, все олимпиады с профилями и фильтрами, свободный ввод
и запасной полнотекстовый поиск. Порядок элементов в списках тоже должен совпадать.
Поля, которых в прототипе не было, допустимы только с пустыми значениями.
Код возврата 1, если нашлись расхождения.
"""

import argparse
import asyncio
import json
import logging
import sys
from typing import Any
from urllib.parse import urlencode

import httpx

QUERIES = [
    "всош",
    "пвг",
    "вышка",
    "высшая проба",
    "нто",
    "мош",
    "оммо",
    "мфти",
    "покори воробьевы",
    "ломоносов",
    "физтех",
    "технологическая",
    "международная",
    "олимпиада",
    "проба",
    "сибирская",
    "спбгу",
    "курчатов",
    "звезда",
    "изумруд",
    "финатлон",
    "росатом",
    "ии",
    "робототехника",
    "информатика",
    "абракадабра",
    "высшая-проба",
    "«Высшая проба»",
]
# поля, которые меняются от сборки к сборке
VOLATILE = {"built_at"}


def path(base: str, **params: Any) -> str:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    return f"{base}?{query}" if query else base


def empty(value: Any) -> bool:
    return value in (None, "", 0, False, [], {})


def diff(old: Any, new: Any, where: str = "") -> list[str]:
    if isinstance(old, dict) and isinstance(new, dict):
        out: list[str] = []
        for key, value in old.items():
            if key in VOLATILE:
                continue
            if key not in new:
                out.append(f"{where}.{key}: нет в новом API")
            else:
                out += diff(value, new[key], f"{where}.{key}")
        out += [
            f"{where}.{key}: лишнее поле = {new[key]!r}"[:200]
            for key in new
            if key not in old and not empty(new[key])
        ]
        return out
    if isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            return [f"{where}: длина {len(old)} != {len(new)}"]
        out = []
        for i, (a, b) in enumerate(zip(old, new, strict=True)):
            out += diff(a, b, f"{where}[{i}]")
            if len(out) > 5:
                break
        return out
    if old != new:
        return [f"{where}: {old!r} != {new!r}"[:300]]
    return []


class Comparer:
    def __init__(self, old: httpx.AsyncClient, new: httpx.AsyncClient, new_prefix: str) -> None:
        self.old, self.new, self.new_prefix = old, new, new_prefix
        self.checked = 0
        self.failed: list[tuple[str, list[str]]] = []
        self.limit = asyncio.Semaphore(8)

    async def get(self, client: httpx.AsyncClient, url: str) -> Any:
        for attempt in range(3):
            try:
                response = await client.get(url, timeout=60)
                return response.status_code, response.json()
            except (httpx.TransportError, json.JSONDecodeError):
                if attempt == 2:
                    raise
                await asyncio.sleep(1)
        return None

    async def check(self, url: str) -> Any:
        async with self.limit:
            (old_status, old), (new_status, new) = await asyncio.gather(
                self.get(self.old, url), self.get(self.new, self.new_prefix + url)
            )
        self.checked += 1
        problems = [f"HTTP {old_status} != {new_status}"] if old_status != new_status else []
        if old_status == 200 and new_status == 200:
            problems += diff(old, new)
        if problems:
            self.failed.append((url, problems))
        return old

    async def run(self, quick: bool) -> None:
        await asyncio.gather(
            *(self.check(u) for u in ("/stats", "/regions", "/olympiads", "/universities")),
            *(self.check(path("/universities", region=r)) for r in ("Москва", "Регионы", "Все")),
            self.check(path("/universities", q="МГУ")),
            self.check(path("/olympiads", limit=12)),
            self.check(path("/olympiads", featured="true", limit=50)),
            *(self.check(path("/olympiads", q=q, limit=8)) for q in QUERIES),
            *(self.check(path("/olympiads", q=q, limit=20)) for q in QUERIES),
            *(self.check(path("/search/by-olympiad", q=q)) for q in QUERIES),
            self.check(path("/search/by-program", program_id=999999)),
        )

        universities = (await self.check("/universities"))["items"]
        programs: list[int] = []
        for chunk in await asyncio.gather(
            *(self.check(path("/programs", university_id=u["id"])) for u in universities),
            *(self.check(path("/programs", university_id=u["id"], q="мат")) for u in universities),
        ):
            programs += [p["id"] for p in chunk["items"]]
        programs = sorted(set(programs))[:: 7 if quick else 1]
        await asyncio.gather(
            *(self.check(path("/search/by-program", program_id=p)) for p in programs)
        )

        olympiads = (await self.check(path("/olympiads", limit=200)))["items"][:: 5 if quick else 1]
        await asyncio.gather(*(self.check(f"/olympiads/{o['id']}/profiles") for o in olympiads))

        async def by_olympiad(o: dict[str, Any]) -> None:
            base = {"q": o["short_name"], "olympiad_id": o["id"]}
            found = await self.check(path("/search/by-olympiad", **base))
            await asyncio.gather(
                *(
                    self.check(path("/search/by-olympiad", **base, benefit_type=t))
                    for t in ("БВИ", "100 баллов")
                ),
                self.check(path("/search/by-olympiad", **base, region="Москва")),
                *(
                    self.check(path("/search/by-olympiad", **base, profile_id=p["id"]))
                    for p in found["profiles"][:3]
                ),
                *(
                    self.check(
                        path("/search/by-olympiad", **base, university_id=r["university"]["id"])
                    )
                    for r in found["results"][:3]
                ),
            )
            if found["profiles"] and found["results"]:
                await self.check(
                    path(
                        "/search/by-olympiad",
                        **base,
                        profile_id=found["profiles"][0]["id"],
                        university_id=found["results"][0]["university"]["id"],
                    )
                )

        await asyncio.gather(*(by_olympiad(o) for o in olympiads))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--old", default="http://localhost:8000/api", help="API прототипа")
    parser.add_argument("--new", default="", help="адрес нового API (по умолчанию — в процессе)")
    parser.add_argument("--quick", action="store_true", help="только часть направлений и олимпиад")
    parser.add_argument("--show", type=int, default=15, help="сколько расхождений показать")
    args = parser.parse_args()

    if args.new:
        new_client = httpx.AsyncClient()
        prefix = args.new.rstrip("/")
    else:
        from olymp_api.main import create_app
        from olymp_api.settings import Settings
        from olymp_db.session import database_url

        app = create_app(Settings(database_url=database_url(), rate_limit_requests=0))
        logging.getLogger("httpx").setLevel(logging.WARNING)
        new_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://new"
        )
        prefix = "/v1"

    async with httpx.AsyncClient(base_url=args.old.rstrip("/")) as old_client, new_client:
        comparer = Comparer(old_client, new_client, prefix)
        await comparer.run(args.quick)

    print(f"Сравнено запросов: {comparer.checked}, с расхождениями: {len(comparer.failed)}")
    for url, problems in comparer.failed[: args.show]:
        print(f"\n{url}")
        for line in problems[:6]:
            print(f"   {line}")
    return 1 if comparer.failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
