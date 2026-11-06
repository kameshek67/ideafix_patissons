"""Кэш и лимиты на Redis. Redis необязателен: без него API работает напрямую с PostgreSQL."""

import json
import time
from typing import Any

import structlog
from fastapi import Request

log = structlog.get_logger()


def make_redis(url: str | None) -> Any:
    if not url:
        return None
    from redis.asyncio import Redis

    return Redis.from_url(url, socket_timeout=0.2, socket_connect_timeout=0.2)


async def cache_get(request: Request, key: str) -> Any | None:
    client = request.app.state.redis
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except Exception:  # noqa: BLE001 - сбой Redis не должен ронять запрос
        log.warning("redis_unavailable", op="cache_get")
        return None
    return json.loads(raw) if raw else None


async def cache_set(request: Request, key: str, value: Any, ttl: int) -> None:
    client = request.app.state.redis
    if client is None:
        return
    try:
        await client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
    except Exception:  # noqa: BLE001
        log.warning("redis_unavailable", op="cache_set")


class LocalWindow:
    """Запасной счётчик запросов в памяти процесса (когда Redis недоступен)."""

    def __init__(self) -> None:
        self.hits: dict[str, tuple[float, int]] = {}

    def hit(self, key: str, window: int) -> tuple[int, int]:
        now = time.monotonic()
        start, count = self.hits.get(key, (now, 0))
        if now - start >= window:
            start, count = now, 0
        count += 1
        self.hits[key] = (start, count)
        if len(self.hits) > 10_000:  # не растём бесконечно
            self.hits = {k: v for k, v in self.hits.items() if now - v[0] < window}
        return count, max(1, int(window - (now - start)))


async def hit(request: Request, key: str, window: int) -> tuple[int, int]:
    """Возвращает (число запросов в окне, секунд до сброса)."""
    client = request.app.state.redis
    if client is not None:
        try:
            bucket = f"rl:{key}:{int(time.time() // window)}"
            count = await client.incr(bucket)
            if count == 1:
                await client.expire(bucket, window)
            return int(count), window - int(time.time() % window)
        except Exception:  # noqa: BLE001
            log.warning("redis_unavailable", op="rate_limit")
    result: tuple[int, int] = request.app.state.local_window.hit(key, window)
    return result
