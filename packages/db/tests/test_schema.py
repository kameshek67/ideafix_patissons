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
