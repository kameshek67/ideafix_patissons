"""olymp-sources: разбор новых документов вузов.

olymp-sources add https://pk.mpei.ru/docs/app2_26.pdf --university "НИУ «МЭИ»"
olymp-sources run 12        # выполнить задачу здесь и сейчас
olymp-sources list          # задачи и их статусы
olymp-sources accept 12     # принять записи (потом worker или rebuild пересоберёт базу)
olymp-sources reject 12
olymp-sources worker        # цикл: берёт очередь из таблицы раз в 10 секунд
olymp-sources rebuild       # пересобрать базу, если есть принятые, но не учтённые задачи
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import psycopg
from olymp_db.session import database_url, psycopg_dsn

from olymp_workers.ai.documents import DocumentStore
from olymp_workers.tls import web_context

from . import jobs

POLL_SECONDS = 10
RETRY_REBUILD_SECONDS = 300


def make_store(cache: Path) -> DocumentStore:
    # сайты вузов часто подписаны сертификатом Минцифры: берём его из OLYMP_MAX_CA_DIR (tls.py)
    return DocumentStore(cache, context=web_context(os.environ.get("OLYMP_INSECURE_FETCH") == "1"))


def process_queue(conn: psycopg.Connection[Any], notify: jobs.Notifier | None) -> int:
    """Выполняет все задачи из очереди; -> сколько выполнено."""
    done = 0
    jobs.recover_stuck(conn)
    while (job_id := jobs.claim_next(conn)) is not None:
        # кэш на задачу: страница могла измениться с прошлого раза
        with tempfile.TemporaryDirectory(prefix="olymp-sources-") as cache:
            store = make_store(Path(cache))
            try:
                jobs.run_job(conn, job_id, store, notify)
            finally:
                store.close()
        done += 1
    return done


def worker(url: str, *, once: bool = False) -> int:
    notify = jobs.webhook_notifier()
    retry_at = 0.0
    with psycopg.connect(psycopg_dsn(url)) as conn:
        while True:
            try:
                process_queue(conn, notify)
                if time.monotonic() >= retry_at and jobs.rebuild_pending(conn) is False:
                    retry_at = time.monotonic() + RETRY_REBUILD_SECONDS
            except psycopg.Error:
                logging.getLogger("olymp.sources").exception("база недоступна")
                conn.rollback()
            if once:
                return 0
            time.sleep(POLL_SECONDS)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="olymp-sources", description=__doc__.split("\n")[0])
    ap.add_argument(
        "--database-url", default=database_url(), help="по умолчанию OLYMP_DATABASE_URL"
    )
    sub = ap.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="поставить ссылку на разбор")
    add.add_argument("url")
    add.add_argument("--university", required=True)
    for name in ("run", "accept", "reject"):
        sub.add_parser(name).add_argument("job_id", type=int)
    sub.add_parser("list")
    sub.add_parser("rebuild")
    w = sub.add_parser("worker")
    w.add_argument("--once", action="store_true", help="разобрать очередь и выйти")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    url = args.database_url
    if args.command == "worker":
        return worker(url, once=args.once)
    with psycopg.connect(psycopg_dsn(url)) as conn:
        try:
            if args.command == "add":
                _, job_id, new = jobs.enqueue(conn, args.url, args.university, "консоль")
                print(f"задача {job_id}" + ("" if new else " (уже в работе)"))
            elif args.command == "run":
                with tempfile.TemporaryDirectory(prefix="olymp-sources-") as cache:
                    store = make_store(Path(cache))
                    try:
                        status = jobs.run_job(conn, args.job_id, store, jobs.webhook_notifier())
                    finally:
                        store.close()
                print(f"задача {args.job_id}: {status}")
                _show(conn, args.job_id)
            elif args.command == "accept":
                count = jobs.accept_job(conn, args.job_id, "консоль")
                print(
                    f"принято записей: {count}; базу пересоберёт worker или olymp-sources rebuild"
                )
            elif args.command == "reject":
                jobs.reject_job(conn, args.job_id)
                print("отклонено")
            elif args.command == "rebuild":
                result = jobs.rebuild_pending(conn)
                print("пересборка не нужна" if result is None else f"пересборка: {result}")
                return 0 if result in (None, True) else 1
            else:
                _show(conn, None)
        except (KeyError, ValueError) as exc:
            print(
                exc.args[0] if isinstance(exc, ValueError) else f"нет задачи {exc}", file=sys.stderr
            )
            return 1
    return 0


def _show(conn: psycopg.Connection[Any], job_id: int | None) -> None:
    rows = conn.execute(
        """SELECT j.id, j.status, s.university, s.url, j.records_count, j.error, j.diff
           FROM source_jobs j JOIN sources s ON s.id = j.source_id
           WHERE (%s::int IS NULL OR j.id = %s) ORDER BY j.id DESC LIMIT 30""",
        (job_id, job_id),
    ).fetchall()
    for jid, status, university, src, records, error, diff in rows:
        line = f"{jid:>4} {status:<10} {university[:30]:<30} записей: {records:<4} {src[:60]}"
        if error:
            line += f"  — {error}"
        print(line)
        if job_id is not None and diff:
            print(
                f"     добавится {diff['added']}, пропадёт {diff['removed']}, "
                f"изменится {diff['changed']}, без изменений {diff['same']}"
            )


if __name__ == "__main__":
    raise SystemExit(main())
