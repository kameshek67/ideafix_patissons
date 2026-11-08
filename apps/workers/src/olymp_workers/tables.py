"""Очистка таблиц сборки без блокировки API (T-064).

TRUNCATE берёт исключительную блокировку таблиц до конца транзакции: пока шла сборка (около
минуты), каждый запрос API к этим таблицам ждал. DELETE блокирует только строки, а читатели по
MVCC до коммита видят прежние данные — API отвечает всё время сборки, новые данные появляются
разом при коммите.

CASCADE не нужен и опасен: он молча очистил бы таблицу пользователей с внешним ключом на данные
сборки. С DELETE такая таблица остановит сборку ошибкой внешнего ключа, а тест в
packages/db/tests/test_schema.py не даёт такую таблицу завести.
"""

from collections.abc import Sequence
from typing import Any

import psycopg


def clear_tables(conn: psycopg.Connection[Any], tables: Sequence[str]) -> None:
    """Удаляет строки (сначала зависимые таблицы — порядок списка) и сбрасывает счётчики id.

    Счётчики сбрасываются, как RESTART IDENTITY: при той же сборке id выходят те же, и ссылки
    вида ?startapp=olympiad-21 переживают пересборку. Удалённые в этой же транзакции строки
    не мешают вставить те же id заново.
    """
    for table in tables:
        conn.execute(f"DELETE FROM {table}")  # noqa: S608 - имена из DATA_TABLES, не от пользователя
    sequences = conn.execute(
        """SELECT pg_get_serial_sequence(format('%%I', c.table_name), c.column_name)
           FROM information_schema.columns c
           WHERE c.table_schema = 'public' AND c.table_name = ANY(%s)
             AND (c.column_default LIKE 'nextval(%%' OR c.is_identity = 'YES')""",
        (list(tables),),
    ).fetchall()
    for (sequence,) in sequences:
        if sequence:  # с начального значения последовательности, как RESTART IDENTITY
            conn.execute(
                """SELECT setval(%s, seqstart, false) FROM pg_sequence
                   WHERE seqrelid = %s::regclass""",
                (sequence, sequence),
            )
