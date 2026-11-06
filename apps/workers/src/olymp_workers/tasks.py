"""Фоновые задачи (Dramatiq + RabbitMQ).

Воркер:            dramatiq olymp_workers.tasks
Поставить задачу:  python -m olymp_workers.tasks refresh-sources [--only кфу]
                   python -m olymp_workers.tasks rebuild

Те же действия доступны и без очереди: olymp-refresh-sources, olymp-ingest.
"""

import argparse
import os
import sys

import dramatiq
from dramatiq.brokers.rabbitmq import RabbitmqBroker

RABBITMQ_URL = os.environ.get("OLYMP_RABBITMQ_URL", "amqp://olymp:olymp@localhost:5672/")
# обход сайтов и сборка базы идут минутами
TIME_LIMIT_MS = 30 * 60 * 1000

dramatiq.set_broker(RabbitmqBroker(url=RABBITMQ_URL))


@dramatiq.actor(queue_name="olymp", max_retries=0, time_limit=TIME_LIMIT_MS)
def refresh_sources(only: str = "") -> None:
    """Обойти страницы приёмных комиссий и обновить ссылки на документы."""
    from .refresh_sources import refresh

    refresh(only=only)


@dramatiq.actor(queue_name="olymp", max_retries=0, time_limit=TIME_LIMIT_MS)
def rebuild_database() -> None:
    """Пересобрать базу из XLSX (одной транзакцией: API видит старые данные до коммита)."""
    from .ingest import DEFAULT_XLSX, Ingestor

    Ingestor(os.environ.get("XLSX_PATH", DEFAULT_XLSX)).run()


def main() -> int:
    parser = argparse.ArgumentParser(description="Поставить фоновую задачу в очередь")
    sub = parser.add_subparsers(dest="task", required=True)
    refresh = sub.add_parser("refresh-sources", help="обновить ссылки на документы вузов")
    refresh.add_argument("--only", default="", help="подстрока названия вуза")
    sub.add_parser("rebuild", help="пересобрать базу из XLSX")
    args = parser.parse_args()

    if args.task == "refresh-sources":
        message = refresh_sources.send(args.only)
    else:
        message = rebuild_database.send()
    print(f"Задача поставлена в очередь: {message.actor_name} ({message.message_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
