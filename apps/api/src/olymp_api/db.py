"""Асинхронный доступ к PostgreSQL: движок, сессия на запрос, короткие помощники для SQL."""

from collections.abc import AsyncIterator, Mapping
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .settings import Settings

Row = dict[str, Any]


def make_engine(settings: Settings) -> AsyncEngine | None:
    if not settings.database_url:
        return None
    url = settings.database_url.replace("+psycopg", "+asyncpg")
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://")
    return create_async_engine(url, pool_size=10, max_overflow=10, pool_pre_ping=True)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] | None = request.app.state.session_factory
    if factory is None:
        raise HTTPException(503, "База данных не настроена")
    async with factory() as session:
        yield session


async def fetch_all(
    session: AsyncSession, sql: str, params: Mapping[str, Any] | None = None
) -> list[Row]:
    result = await session.execute(text(sql), dict(params or {}))
    return [dict(row) for row in result.mappings().all()]


async def fetch_one(
    session: AsyncSession, sql: str, params: Mapping[str, Any] | None = None
) -> Row | None:
    rows = await fetch_all(session, sql, params)
    return rows[0] if rows else None


async def scalar(session: AsyncSession, sql: str, params: Mapping[str, Any] | None = None) -> Any:
    return await session.scalar(text(sql), dict(params or {}))


async def data_version(session: AsyncSession) -> str:
    """Время сборки базы: входит в ключи кэша, чтобы пересборка его сбрасывала."""
    built = await scalar(session, "SELECT value FROM meta WHERE key = 'built_at'")
    if built is None:
        raise HTTPException(503, "База ещё не собрана: запустите olymp-ingest")
    return str(built)
