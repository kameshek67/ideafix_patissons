"""Очистка таблиц сборки: без блокировки читателей и с теми же id после пересборки (T-064)."""

import threading
import time

import psycopg
from olymp_db.session import psycopg_dsn
from olymp_workers.tables import clear_tables

INSERT = "INSERT INTO universities (name, short_name) VALUES (%s, %s) RETURNING id"


def test_ids_restart_and_readers_see_old_rows(empty_database_url: str) -> None:
    dsn = psycopg_dsn(empty_database_url)
    with psycopg.connect(dsn) as conn:
        clear_tables(conn, ["universities"])  # база общая на прогон: начинаем с чистой таблицы
        first = [conn.execute(INSERT, (name, name)).fetchone()[0] for name in ("А", "Б")]
        conn.commit()

        clear_tables(conn, ["universities"])
        # чужое соединение во время незавершённой пересборки: не ждёт и видит прежние строки
        seen: list[tuple[int, float]] = []

        def read() -> None:
            started = time.perf_counter()
            with psycopg.connect(dsn) as reader:
                count = reader.execute("SELECT count(*) FROM universities").fetchone()[0]
            seen.append((count, time.perf_counter() - started))

        thread = threading.Thread(target=read)
        thread.start()
        thread.join(timeout=10)
        assert seen and seen[0][0] == 2 and seen[0][1] < 5

        again = [conn.execute(INSERT, (name, name)).fetchone()[0] for name in ("А", "Б")]
        conn.commit()
        clear_tables(conn, ["universities"])
        conn.commit()
    assert again == first == [1, 2]
