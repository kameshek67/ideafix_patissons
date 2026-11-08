"""Запрос не висит, пока таблица заблокирована: таймаут БД — быстрый ответ 503 (T-064)."""

import time
from collections.abc import AsyncIterator

import httpx
import psycopg
import pytest
from olymp_api.db import make_engine
from olymp_api.errors import is_db_timeout
from olymp_api.main import create_app
from olymp_api.settings import Settings
from olymp_db.session import psycopg_dsn
from sqlalchemy import text


def settings(url: str, **changes: int) -> Settings:
    return Settings(_env_file=None, database_url=url, rate_limit_requests=0, **changes)


async def test_statement_timeout_is_recognised(empty_database_url: str) -> None:
    engine = make_engine(settings(empty_database_url, db_statement_timeout_ms=50))
    assert engine is not None
    with pytest.raises(Exception) as caught:  # noqa: PT011 - тип зависит от драйвера
        async with engine.connect() as conn:
            await conn.execute(text("SELECT pg_sleep(1)"))
    await engine.dispose()
    assert is_db_timeout(caught.value)
    assert not is_db_timeout(ValueError("другое"))


@pytest.fixture
async def locked_client(empty_database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    """Клиент API, пока чужая транзакция держит исключительную блокировку таблицы вузов."""
    app = create_app(settings(empty_database_url, db_lock_timeout_ms=200))
    with psycopg.connect(psycopg_dsn(empty_database_url)) as lock:
        lock.execute("LOCK TABLE universities IN ACCESS EXCLUSIVE MODE")
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
        lock.rollback()
    await app.state.engine.dispose()


async def test_locked_table_gives_fast_503(locked_client: httpx.AsyncClient) -> None:
    started = time.perf_counter()
    response = await locked_client.get("/v1/universities")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert time.perf_counter() - started < 5
