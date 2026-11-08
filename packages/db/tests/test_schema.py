import psycopg
from olymp_db.models import DATA_TABLES, Base
from olymp_db.session import psycopg_dsn


def test_migrations_create_all_tables(empty_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        tables = {
            r[0]
            for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        }
    assert set(Base.metadata.tables) <= tables
    assert set(DATA_TABLES) <= tables


def test_text_columns_sort_bytewise(empty_database_url: str) -> None:
    """Сортировка «C» у текстовых колонок: порядок строк как в прототипе на SQLite."""
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        rows = conn.execute(
            """SELECT table_name, column_name, collation_name FROM information_schema.columns
               WHERE table_schema = 'public' AND data_type = 'text'"""
        ).fetchall()
    assert rows
    assert {r[2] for r in rows} == {"C"}, [r for r in rows if r[2] != "C"]


def test_check_constraints(empty_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'benefits'::regclass"
            )
        }
    assert {"ck_benefits_benefit_type", "ck_benefits_layer"} <= names


def _foreign_keys(url: str) -> list[tuple[str, str]]:
    """(таблица, на какую таблицу ссылается) — по схеме после миграций, а не по моделям."""
    with psycopg.connect(psycopg_dsn(url)) as conn:
        return conn.execute(
            """SELECT conrelid::regclass::text, confrelid::regclass::text
               FROM pg_constraint WHERE contype = 'f' AND connamespace = 'public'::regnamespace"""
        ).fetchall()


def test_user_tables_do_not_reference_build_tables(empty_database_url: str) -> None:
    """Пересборка удаляет строки таблиц сборки: ссылка на них из данных пользователей либо
    остановила бы сборку, либо (с CASCADE) молча удалила бы дипломы и ссылки (T-064)."""
    bad = [
        (child, parent)
        for child, parent in _foreign_keys(empty_database_url)
        if child not in DATA_TABLES and parent in DATA_TABLES
    ]
    assert bad == [], "храните стабильные ключи (squash), а не id таблиц сборки"


def test_build_tables_are_listed_children_first(empty_database_url: str) -> None:
    """clear_tables удаляет по порядку DATA_TABLES: зависимая таблица — раньше той, на которую
    ссылается, иначе DELETE упрётся во внешний ключ."""
    order = {name: i for i, name in enumerate(DATA_TABLES)}
    wrong = [
        (child, parent)
        for child, parent in _foreign_keys(empty_database_url)
        if child in order and parent in order and child != parent and order[child] > order[parent]
    ]
    assert wrong == []
