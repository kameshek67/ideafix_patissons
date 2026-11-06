"""Общие фикстуры тестов: временные базы PostgreSQL с миграциями.

Нужен запущенный PostgreSQL (`just up`); адрес администратора — OLYMP_TEST_DATABASE_URL
(по умолчанию olymp:olymp@localhost:5432). Если сервера нет, тесты с базой пропускаются.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from olymp_db.session import DEFAULT_URL
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parent
DB_DIR = ROOT / "packages" / "db"
XLSX = ROOT / "data" / "Olimpiady_BVI_100ballov.xlsx"


def _admin_url() -> URL:
    return make_url(os.environ.get("OLYMP_TEST_DATABASE_URL", DEFAULT_URL))


def _create_database(prefix: str) -> tuple[URL, str]:
    admin = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL недоступен: {exc.__class__.__name__}")
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    return _admin_url().set(database=name), name


def _drop_database(name: str) -> None:
    admin = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


def migrate(url: URL) -> None:
    engine = create_engine(url)
    cfg = Config(str(DB_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(DB_DIR / "src" / "olymp_db" / "migrations"))
    cfg.attributes["engine"] = engine
    command.upgrade(cfg, "head")
    engine.dispose()


@pytest.fixture(scope="session")
def empty_database_url() -> Iterator[str]:
    """Свежая база с применёнными миграциями и без данных."""
    url, name = _create_database("olymp_test_empty")
    migrate(url)
    yield url.render_as_string(hide_password=False)
    _drop_database(name)


@pytest.fixture(scope="session")
def built_database_url() -> Iterator[str]:
    """База, собранная из настоящего XLSX — один раз на весь прогон тестов."""
    from olymp_workers.ingest import Ingestor

    url, name = _create_database("olymp_test_built")
    migrate(url)
    rendered = url.render_as_string(hide_password=False)
    Ingestor(str(XLSX), rendered).run()
    yield rendered
    _drop_database(name)
