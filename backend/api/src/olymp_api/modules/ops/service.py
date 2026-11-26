import json
from typing import Any

from fastapi import HTTPException
from olymp_domain.urls import normalize_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import fetch_all, fetch_one

ACTIVE = ("queued", "fetching", "extracting", "review")
JOB_COLUMNS = """j.id, j.source_id, s.university, s.url, j.status, j.error, j.records_count,
    j.quotes_checked, j.quotes_found, j.rebuild_needed, j.created_at, j.updated_at"""
JOB_FROM = "FROM source_jobs j JOIN sources s ON s.id = j.source_id"


async def add_source(
    session: AsyncSession, url: str, university: str, added_by: str
) -> tuple[int, int, bool]:
    try:
        url = normalize_url(url)
    except ValueError:
        raise HTTPException(422, "Ссылка должна начинаться с http:// или https://") from None
    university = " ".join(university.split())
    if len(university) < 2:
        raise HTTPException(422, "Укажи вуз")
    kind = "document" if url.lower().split("?")[0].endswith((".pdf", ".xlsx", ".xls")) else "page"
    source = await fetch_one(
        session,
        """INSERT INTO sources (university, url, kind, added_by)
           VALUES (:university, :url, :kind, :by)
           ON CONFLICT (url) DO NOTHING RETURNING id""",
        {"university": university, "url": url, "kind": kind, "by": added_by},
    )
    if source is None:
        existing = await fetch_one(
            session, "SELECT id, university FROM sources WHERE url = :url", {"url": url}
        )
        assert existing is not None
        if existing["university"] != university:
            raise HTTPException(
                409,
                f"Ссылка уже добавлена с вузом «{existing['university']}», а указан «{university}»",
            )
        source = existing
    active = await fetch_one(
        session,
        "SELECT id FROM source_jobs WHERE source_id = :s AND status = ANY(:active)"
        " ORDER BY id LIMIT 1",
        {"s": source["id"], "active": list(ACTIVE)},
    )
    if active:
        await session.commit()
        return source["id"], active["id"], False
    job = await fetch_one(
        session,
        "INSERT INTO source_jobs (source_id) VALUES (:s) RETURNING id",
        {"s": source["id"]},
    )
    assert job is not None
    await session.commit()
    return source["id"], job["id"], True


async def list_sources(session: AsyncSession) -> list[dict[str, Any]]:
    return await fetch_all(
        session,
        """SELECT s.id, s.university, s.url, s.kind, s.created_at, s.last_checked_at,
                  lj.id AS last_job_id, lj.status AS last_job_status
           FROM sources s
           LEFT JOIN LATERAL (SELECT id, status FROM source_jobs WHERE source_id = s.id
                              ORDER BY id DESC LIMIT 1) lj ON true
           ORDER BY s.id DESC LIMIT 200""",
    )


async def list_jobs(session: AsyncSession, status: str | None, limit: int) -> list[dict[str, Any]]:
    return await fetch_all(
        session,
        f"SELECT {JOB_COLUMNS} {JOB_FROM} WHERE (CAST(:status AS text) IS NULL OR j.status = :status)"
        " ORDER BY j.id DESC LIMIT :limit",
        {"status": status, "limit": limit},
    )


async def get_job(session: AsyncSession, job_id: int) -> dict[str, Any]:
    row = await fetch_one(
        session,
        f"SELECT {JOB_COLUMNS}, j.documents, j.diff {JOB_FROM} WHERE j.id = :id",
        {"id": job_id},
    )
    if row is None:
        raise HTTPException(404, "Задача не найдена")
    return row


async def decide(session: AsyncSession, job_id: int, accept: bool) -> dict[str, Any]:
    """Принять записи задачи в document_records (как accept_document в воркерах) или отклонить."""
    job = await fetch_one(
        session,
        "SELECT status, payload FROM source_jobs WHERE id = :id FOR UPDATE",
        {"id": job_id},
    )
    if job is None:
        raise HTTPException(404, "Задача не найдена")
    if job["status"] != "review":
        raise HTTPException(409, "Решение принимается только по задаче на проверке")
    records = 0
    if accept:
        for item in job["payload"]:
            doc = item["document"]
            await session.execute(
                text("DELETE FROM document_records WHERE document_url = :url"), {"url": doc["url"]}
            )
            for rec in item["records"]:
                await session.execute(
                    text(
                        """INSERT INTO document_records
                           (document_url, document_sha256, document_title, university, campaign,
                            record, accepted_by, origin)
                           VALUES (:url, :sha, :title, :uni, :campaign, CAST(:record AS jsonb),
                                   'ops api', 'operator')"""
                    ),
                    {
                        "url": doc["url"],
                        "sha": doc["sha256"],
                        "title": doc.get("title", ""),
                        "uni": doc["university"],
                        "campaign": doc["campaign"],
                        "record": json.dumps(rec, ensure_ascii=False),
                    },
                )
                records += 1
    status = "accepted" if accept else "rejected"
    await session.execute(
        text(
            "UPDATE source_jobs SET status = :status, rebuild_needed = :rebuild, updated_at = now()"
            " WHERE id = :id"
        ),
        {"status": status, "rebuild": accept, "id": job_id},
    )
    await session.commit()
    return {"id": job_id, "status": status, "records": records}
