"""Лимит запросов считает посетителя, а не прокси, и не обходится подменой X-Forwarded-For (T-065)."""

import httpx
from olymp_api.main import create_app
from olymp_api.settings import Settings


def client(peer: str) -> httpx.AsyncClient:
    # без базы: /v1/regions отвечает 503, но лимит срабатывает раньше и отдаёт 429
    app = create_app(Settings(_env_file=None, database_url=None, rate_limit_requests=2))
    transport = httpx.ASGITransport(app=app, client=(peer, 1234))
    return httpx.AsyncClient(transport=transport, base_url="http://t")


async def codes(c: httpx.AsyncClient, forwarded: str, n: int = 3) -> list[int]:
    headers = {"x-forwarded-for": forwarded}
    return [(await c.get("/v1/regions", headers=headers)).status_code for _ in range(n)]


async def test_visitors_behind_proxy_are_counted_apart() -> None:
    async with client("172.18.0.5") as c:  # запрос от контейнера сайта
        first = await codes(c, "203.0.113.1")
        second = await codes(c, "203.0.113.2")
    assert first == [503, 503, 429]
    assert second == [503, 503, 429]  # у второго посетителя свой счётчик


async def test_spoofed_left_part_does_not_reset_limit() -> None:
    async with client("172.18.0.5") as c:
        spoofed = [
            (
                await c.get("/v1/regions", headers={"x-forwarded-for": f"10.0.0.{i}, 203.0.113.9"})
            ).status_code
            for i in range(3)
        ]
    assert spoofed[-1] == 429


async def test_public_peer_header_is_ignored() -> None:
    """Напрямую из интернета X-Forwarded-For не принимается: лимит — по адресу соединения."""
    async with client("198.51.100.7") as c:
        rotated = [
            (await c.get("/v1/regions", headers={"x-forwarded-for": f"203.0.113.{i}"})).status_code
            for i in range(3)
        ]
    assert rotated[-1] == 429
