# -*- coding: utf-8 -*-
"""Доступ к SQLite: одно соединение на процесс, read-only режим для API."""

from __future__ import annotations

import os
import sqlite3
import threading
from typing import Any, Dict, Iterable, List, Optional, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(HERE, "..", "data", "bvi_database.db"))

_local = threading.local()


def db_path() -> str:
    return os.path.abspath(DB_PATH)


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        if not os.path.exists(db_path()):
            raise RuntimeError(
                f"База не найдена: {db_path()}. Сначала выполните `python ingest_data.py`."
            )
        conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        _local.conn = conn
    return conn


def query(sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    cur = get_conn().execute(sql, tuple(params))
    return [dict(row) for row in cur.fetchall()]


def query_one(sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
    rows = query(sql, params)
    return rows[0] if rows else None


def scalar(sql: str, params: Sequence[Any] = ()) -> Any:
    row = get_conn().execute(sql, tuple(params)).fetchone()
    return row[0] if row else None


def fts_enabled() -> bool:
    try:
        return scalar("SELECT value FROM meta WHERE key='fts'") == "on"
    except sqlite3.Error:
        return False
