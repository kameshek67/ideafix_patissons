"""Принятые записи о льготах из документов вузов (таблица document_records).

Таблица не входит в DATA_TABLES: пересборка её не стирает. Сборка читает её вместе с файлами
data/extracted (document_layer.py); оператор принимает набор записей документа через accept_document.
"""

from __future__ import annotations

from typing import Any

import psycopg
from olymp_domain.extraction import ExtractionFile
from psycopg.types.json import Jsonb


def accept_document(
    conn: psycopg.Connection[Any],
    extraction: ExtractionFile,
    *,
    accepted_by: str = "",
    origin: str = "operator",
) -> int:
    """Принимает набор записей документа: прежние записи того же url заменяются новыми.

    Пустой набор убирает документ. Возвращает число принятых записей. Всё — в транзакции
    вызывающего: коммит и откат за ним."""
    doc = extraction.document
    conn.execute("DELETE FROM document_records WHERE document_url = %s", (doc.url,))
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO document_records
               (document_url, document_sha256, document_title, university, campaign,
                record, accepted_by, origin)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            [
                (
                    doc.url,
                    doc.sha256,
                    doc.title,
                    doc.university,
                    doc.campaign,
                    Jsonb(rec.model_dump(mode="json")),
                    accepted_by,
                    origin,
                )
                for rec in extraction.records
            ],
        )
    return len(extraction.records)
