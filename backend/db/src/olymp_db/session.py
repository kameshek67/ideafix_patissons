import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_URL = "postgresql+psycopg://olymp:olymp@localhost:5432/olymp"


def database_url() -> str:
    """Синхронный URL (psycopg). Для asyncpg API заменяет драйвер сам."""
    url = os.environ.get("OLYMP_DATABASE_URL", DEFAULT_URL)
    return url.replace("+asyncpg", "+psycopg")


def psycopg_dsn(url: str | None = None) -> str:
    """URL для psycopg.connect(): без указания драйвера SQLAlchemy."""
    return (url or database_url()).replace("postgresql+psycopg://", "postgresql://")


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True, pool_size=5, max_overflow=5)


def make_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(engine or make_engine(), expire_on_commit=False)
