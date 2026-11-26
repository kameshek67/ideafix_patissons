"""Очередь задач разбора в таблице source_jobs: постановка, обработка, приём, отклонение.

Очередь — просто таблица: воркер раз в несколько секунд берёт следующую задачу (FOR UPDATE SKIP
LOCKED), RabbitMQ не нужен. После приёма записи ложатся в document_records, а база пересобирается
olymp-ingest (отдельным процессом, чтобы нехватка памяти не уронила воркер).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from collections.abc import Callable
from typing import Any

import httpx
import psycopg
from olymp_domain.extraction import ExtractionFile
from psycopg.types.json import Jsonb

from olymp_workers.ai.documents import DocumentError, DocumentStore, safe_url
from olymp_workers.document_records import accept_document

from .pipeline import JobError, JobResult, run_pipeline

log = logging.getLogger("olymp.sources")
ACTIVE = ("queued", "fetching", "extracting", "review")
STUCK_MINUTES = 30
RE_FILE = re.compile(r"\.(pdf|xlsx?)($|[?#])", re.IGNORECASE)
Notifier = Callable[[dict[str, Any]], None]


def _one(conn: psycopg.Connection[Any], sql: str, params: tuple[Any, ...]) -> tuple[Any, ...]:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        raise KeyError(params[0])
    return tuple(row)


def enqueue(
    conn: psycopg.Connection[Any], url: str, university: str, added_by: str = ""
) -> tuple[int, int, bool]:
    """Источник и задача на него -> (source_id, job_id, новая ли задача).

    Пока по источнику есть незавершённая задача, новая не ставится — возвращается она."""
    try:
        url = safe_url(url)
    except DocumentError as exc:
        raise ValueError(f"ссылка не подходит: {exc}") from None
    university = " ".join(university.split())
    if not university:
        raise ValueError("не указан вуз")
    source_id = _one(
        conn,
        """INSERT INTO sources (university, url, kind, added_by) VALUES (%s, %s, %s, %s)
           ON CONFLICT (url) DO UPDATE SET university = EXCLUDED.university RETURNING id""",
        (university, url, "document" if RE_FILE.search(url) else "page", added_by),
    )[0]
    active = conn.execute(
        "SELECT id FROM source_jobs WHERE source_id = %s AND status = ANY(%s) ORDER BY id LIMIT 1",
        (source_id, list(ACTIVE)),
    ).fetchone()
    if active:
        conn.commit()
        return source_id, active[0], False
    job_id = _one(
        conn, "INSERT INTO source_jobs (source_id) VALUES (%s) RETURNING id", (source_id,)
    )[0]
    conn.commit()
    return source_id, job_id, True


def set_status(conn: psycopg.Connection[Any], job_id: int, status: str, **fields: Any) -> None:
    assignments = ["status = %s", "updated_at = now()", *(f"{name} = %s" for name in fields)]
    values = [status, *(Jsonb(v) if isinstance(v, (dict, list)) else v for v in fields.values())]
    conn.execute(
        f"UPDATE source_jobs SET {', '.join(assignments)} WHERE id = %s", (*values, job_id)
    )
    conn.commit()


def claim_next(conn: psycopg.Connection[Any]) -> int | None:
    row = conn.execute(
        """UPDATE source_jobs SET status = 'fetching', updated_at = now()
           WHERE id = (SELECT id FROM source_jobs WHERE status = 'queued'
                       ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id"""
    ).fetchone()
    conn.commit()
    return row[0] if row else None


def claim_recheck(conn: psycopg.Connection[Any], days: int) -> tuple[int, str, str] | None:
    """Берёт одного любого источника на проверку: строка sources остаётся заблокированной,
    пока проверяющий не зафиксирует результат (или не откатит транзакцию при ошибке)."""
    row = conn.execute(
        """SELECT s.id, s.url, s.last_sha256 FROM sources s
           WHERE s.last_checked_at IS NULL OR s.last_checked_at <= now() - make_interval(days => %s)
           ORDER BY s.id FOR UPDATE OF s SKIP LOCKED LIMIT 1""",
        (days,),
    ).fetchone()
    if row is None:
        conn.commit()
        return None
    return int(row[0]), str(row[1]), str(row[2])


def enqueue_changed(conn: psycopg.Connection[Any], source_id: int) -> int:
    """Задача на изменившийся источник с пометкой причины."""
    return int(
        _one(
            conn,
            "INSERT INTO source_jobs (source_id, error) VALUES (%s, 'документ изменился') RETURNING id",
            (source_id,),
        )[0]
    )


def recover_stuck(conn: psycopg.Connection[Any]) -> int:
    """Задачи, брошенные упавшим воркером, становятся ошибкой, а не висят вечно."""
    rows = conn.execute(
        """UPDATE source_jobs SET status = 'failed', updated_at = now(),
                  error = 'обработка прервалась, поставь ссылку заново'
           WHERE status IN ('fetching', 'extracting')
                 AND updated_at < now() - make_interval(mins => %s) RETURNING id""",
        (STUCK_MINUTES,),
    ).fetchall()
    conn.commit()
    return len(rows)


def webhook_notifier(
    url: str | None = None, transport: httpx.BaseTransport | None = None
) -> Notifier | None:
    url = url if url is not None else os.environ.get("OLYMP_OPS_WEBHOOK_URL", "")
    if not url:
        return None

    def notify(payload: dict[str, Any]) -> None:
        try:
            with httpx.Client(timeout=10, transport=transport) as client:
                client.post(url, json=payload)
        except httpx.HTTPError as exc:
            log.warning("webhook не доставлен: %s", type(exc).__name__)

    return notify


def _announce(conn: psycopg.Connection[Any], job_id: int, notify: Notifier | None) -> None:
    if notify is None:
        return
    status, error, records, university, url = _one(
        conn,
        """SELECT j.status, j.error, j.records_count, s.university, s.url
           FROM source_jobs j JOIN sources s ON s.id = j.source_id WHERE j.id = %s""",
        (job_id,),
    )
    notify(
        {
            "job_id": job_id,
            "status": status,
            "university": university,
            "url": url,
            "records": records,
            "error": error,
        }
    )


def run_job(
    conn: psycopg.Connection[Any], job_id: int, store: DocumentStore, notify: Notifier | None = None
) -> str:
    """Выполняет задачу целиком; возвращает итоговый статус (review или failed)."""
    row = conn.execute(
        "SELECT s.id, s.url, s.university FROM source_jobs j JOIN sources s ON s.id = j.source_id"
        " WHERE j.id = %s",
        (job_id,),
    ).fetchone()
    if row is None:
        raise KeyError(job_id)
    source_id, url, university = row
    set_status(conn, job_id, "fetching", error="")
    try:
        result = run_pipeline(
            conn, store, url, university, lambda status: set_status(conn, job_id, status)
        )
    except JobError as exc:
        conn.rollback()
        set_status(conn, job_id, "failed", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - воркер живёт дальше, оператор видит причину
        log.exception("задача %s упала", job_id)
        conn.rollback()
        set_status(conn, job_id, "failed", error=f"внутренняя ошибка ({type(exc).__name__})")
    else:
        _finish(conn, job_id, source_id, result)
    status = _one(conn, "SELECT status FROM source_jobs WHERE id = %s", (job_id,))[0]
    _announce(conn, job_id, notify)
    return str(status)


def _finish(conn: psycopg.Connection[Any], job_id: int, source_id: int, result: JobResult) -> None:
    conn.execute(
        "UPDATE sources SET kind = %s, last_checked_at = now(), last_sha256 = %s WHERE id = %s",
        (result.kind, result.sha256, source_id),
    )
    set_status(
        conn,
        job_id,
        "review",
        documents=result.documents,
        payload=[json.loads(f.model_dump_json()) for f in result.files],
        records_count=result.records,
        quotes_checked=result.quotes_checked,
        quotes_found=result.quotes_found,
        diff=result.diff,
    )


def accept_job(conn: psycopg.Connection[Any], job_id: int, accepted_by: str = "оператор") -> int:
    """Принимает записи задачи в document_records и просит пересборку. -> число записей."""
    row = conn.execute(
        "SELECT status, payload FROM source_jobs WHERE id = %s FOR UPDATE", (job_id,)
    ).fetchone()
    if row is None:
        raise KeyError(job_id)
    if row[0] != "review":
        raise ValueError("принять можно только задачу на проверке")
    total = 0
    for item in row[1]:
        total += accept_document(
            conn, ExtractionFile.model_validate(item), accepted_by=accepted_by, origin="operator"
        )
    conn.execute(
        "UPDATE source_jobs SET status = 'accepted', rebuild_needed = true, updated_at = now()"
        " WHERE id = %s",
        (job_id,),
    )
    conn.commit()
    return total


def reject_job(conn: psycopg.Connection[Any], job_id: int) -> None:
    row = conn.execute(
        "SELECT status FROM source_jobs WHERE id = %s FOR UPDATE", (job_id,)
    ).fetchone()
    if row is None:
        raise KeyError(job_id)
    if row[0] != "review":
        raise ValueError("отклонить можно только задачу на проверке")
    conn.execute(
        "UPDATE source_jobs SET status = 'rejected', updated_at = now() WHERE id = %s", (job_id,)
    )
    conn.commit()


def run_ingest() -> bool:
    """Пересборка базы так же, как в сервисе migrate (olymp-ingest)."""
    done = subprocess.run([sys.executable, "-m", "olymp_workers.ingest"], check=False)
    return done.returncode == 0


def rebuild_pending(
    conn: psycopg.Connection[Any], runner: Callable[[], bool] = run_ingest
) -> bool | None:
    """Если есть принятые задачи без пересборки — пересобирает базу. None — пересборка не нужна."""
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM source_jobs WHERE status = 'accepted' AND rebuild_needed ORDER BY id"
        ).fetchall()
    ]
    if not ids:
        return None
    ok = runner()
    if ok:
        conn.execute(
            "UPDATE source_jobs SET rebuild_needed = false, rebuilt_at = now() WHERE id = ANY(%s)",
            (ids,),
        )
        conn.commit()
    else:
        log.error("пересборка базы не удалась, повторю позже")
    return ok
