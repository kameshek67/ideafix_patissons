"""Ops API разбора документов: доступ по токену, постановка ссылки, решение по задаче."""

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import psycopg
import pytest
from olymp_api.main import create_app
from olymp_api.settings import Settings
from olymp_db.session import psycopg_dsn

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
URL = "https://example.edu/files/doc.pdf"
SHA = "b" * 64


def client_for(url: str, token: str | None) -> httpx.AsyncClient:
    app = create_app(
        Settings(_env_file=None, database_url=url, rate_limit_requests=0, ops_token=token)
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def ops(empty_database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(empty_database_url, TOKEN) as c:
        yield c
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        conn.execute("DELETE FROM sources")
        conn.execute("DELETE FROM document_records")
        conn.commit()


@pytest.fixture
def db(empty_database_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        yield conn


def extraction() -> dict[str, Any]:
    source = {"url": URL, "sha256": SHA, "page": 1, "quote": "37.03.01 Олимпиада А"}
    return {
        "document": {
            "university": "Вуз",
            "campaign": 2026,
            "url": URL,
            "sha256": SHA,
            "title": "Приложение",
            "pages": [1],
        },
        "records": [
            {
                "university": "Вуз",
                "campaign": 2026,
                "program_code": "37.03.01",
                "benefit_type": "bvi",
                "olympiad": "Олимпиада А",
                "source": source,
            }
        ],
    }


async def test_without_token_in_settings_endpoints_are_hidden(empty_database_url: str) -> None:
    async with client_for(empty_database_url, None) as c:
        for path in ("/v1/ops/sources", "/v1/ops/jobs", "/v1/ops/jobs/1"):
            assert (await c.get(path, headers=AUTH)).status_code == 404


async def test_ops_are_hidden_from_openapi(empty_database_url: str) -> None:
    async with client_for(empty_database_url, TOKEN) as c:
        schema = (await c.get("/openapi.json")).json()
    assert not any(path.startswith("/v1/ops") for path in schema["paths"])
    assert "JobDetail" not in schema["components"]["schemas"]


async def test_token_is_required(ops: httpx.AsyncClient) -> None:
    assert (await ops.get("/v1/ops/jobs")).status_code == 401
    bad = await ops.get("/v1/ops/jobs", headers={"Authorization": "Bearer other"})
    assert bad.status_code == 401
    assert (await ops.get("/v1/ops/jobs", headers=AUTH)).status_code == 200


async def test_non_ascii_token_is_rejected(empty_database_url: str) -> None:
    async with client_for(empty_database_url, "төкен") as c:
        assert (await c.get("/v1/ops/jobs", headers=AUTH)).status_code == 401


async def test_add_source_queues_one_job(ops: httpx.AsyncClient) -> None:
    body = {"url": "https://example.edu/олимпиады/", "university": "  Вуз   Тестовый "}
    first = await ops.post("/v1/ops/sources", json=body, headers=AUTH)
    assert first.status_code == 201 and first.json()["created"] is True
    again = await ops.post("/v1/ops/sources", json=body, headers=AUTH)
    assert again.json() == {**first.json(), "created": False}
    bad = await ops.post(
        "/v1/ops/sources",
        json={"url": "ftp://example.edu/x.pdf", "university": "Вуз"},
        headers=AUTH,
    )
    assert bad.status_code == 422

    listed = (await ops.get("/v1/ops/sources", headers=AUTH)).json()
    assert listed[0]["university"] == "Вуз Тестовый"
    assert (listed[0]["last_job_id"], listed[0]["last_job_status"]) == (
        first.json()["job_id"],
        "queued",
    )
    jobs = (await ops.get("/v1/ops/jobs?status=queued", headers=AUTH)).json()
    assert [j["id"] for j in jobs] == [first.json()["job_id"]]
    assert (await ops.get("/v1/ops/jobs?status=wrong", headers=AUTH)).status_code == 422


async def test_conflicting_university_is_rejected(
    ops: httpx.AsyncClient, db: psycopg.Connection[Any]
) -> None:
    body = {"url": URL, "university": "Вуз Первый"}
    first = await ops.post("/v1/ops/sources", json=body, headers=AUTH)
    assert first.status_code == 201

    conflict = await ops.post(
        "/v1/ops/sources", json={**body, "university": "Вуз Второй"}, headers=AUTH
    )
    assert conflict.status_code == 409
    assert "Вуз Первый" in conflict.json()["title"]
    assert "Вуз Второй" in conflict.json()["title"]

    listed = (await ops.get("/v1/ops/sources", headers=AUTH)).json()
    assert len(listed) == 1 and listed[0]["university"] == "Вуз Первый"
    assert db.execute("SELECT count(*) FROM source_jobs").fetchone() == (1,)


async def make_review_job(ops: httpx.AsyncClient, db: psycopg.Connection[Any]) -> int:
    job_id = (
        await ops.post("/v1/ops/sources", json={"url": URL, "university": "Вуз"}, headers=AUTH)
    ).json()["job_id"]
    diff = {
        "added": 1,
        "removed": 0,
        "changed": 0,
        "same": 0,
        "examples": {"added": [], "removed": [], "changed": []},
    }
    db.execute(
        """UPDATE source_jobs SET status = 'review', records_count = 1, payload = %s::jsonb,
                  diff = %s::jsonb, documents = '[{"url": "u", "records": 1}]'::jsonb WHERE id = %s""",
        (json.dumps([extraction()]), json.dumps(diff), job_id),
    )
    db.commit()
    return job_id


async def test_job_detail_and_accept(ops: httpx.AsyncClient, db: psycopg.Connection[Any]) -> None:
    job_id = await make_review_job(ops, db)
    detail = (await ops.get(f"/v1/ops/jobs/{job_id}", headers=AUTH)).json()
    assert detail["status"] == "review" and detail["diff"]["added"] == 1
    assert "payload" not in detail and detail["documents"][0]["records"] == 1

    done = await ops.post(f"/v1/ops/jobs/{job_id}/accept", headers=AUTH)
    assert done.json() == {"id": job_id, "status": "accepted", "records": 1}
    assert db.execute(
        "SELECT document_url, record->>'olympiad' FROM document_records"
    ).fetchall() == [(URL, "Олимпиада А")]
    assert db.execute(
        "SELECT rebuild_needed FROM source_jobs WHERE id = %s", (job_id,)
    ).fetchone() == (True,)
    assert (await ops.post(f"/v1/ops/jobs/{job_id}/accept", headers=AUTH)).status_code == 409
    assert (await ops.post(f"/v1/ops/jobs/{job_id}/reject", headers=AUTH)).status_code == 409


async def test_reject_keeps_records_out(
    ops: httpx.AsyncClient, db: psycopg.Connection[Any]
) -> None:
    job_id = await make_review_job(ops, db)
    done = await ops.post(f"/v1/ops/jobs/{job_id}/reject", headers=AUTH)
    assert done.json()["status"] == "rejected"
    assert db.execute("SELECT count(*) FROM document_records").fetchone() == (0,)
    assert (await ops.get("/v1/ops/jobs/99999", headers=AUTH)).status_code == 404
    assert (await ops.post("/v1/ops/jobs/99999/accept", headers=AUTH)).status_code == 404


async def test_jobs_carry_grade_origin_and_filter(
    ops: httpx.AsyncClient, db: psycopg.Connection[Any]
) -> None:
    mine = (
        await ops.post("/v1/ops/sources", json={"url": URL, "university": "Вуз"}, headers=AUTH)
    ).json()["job_id"]
    db.execute(
        "UPDATE source_jobs SET grade = 'yellow', grade_reasons = '[\"записей мало: 3\"]' WHERE id = %s",
        (mine,),
    )
    source = db.execute(
        "INSERT INTO sources (university, url, added_by) VALUES ('Вуз', %s, 'user') RETURNING id",
        ("https://example.edu/user.pdf",),
    ).fetchone()
    assert source
    theirs = db.execute(
        "INSERT INTO source_jobs (source_id, origin, comment) VALUES (%s, 'user', 'новые правила')"
        " RETURNING id",
        (source[0],),
    ).fetchone()
    assert theirs
    db.commit()

    jobs = {j["id"]: j for j in (await ops.get("/v1/ops/jobs", headers=AUTH)).json()}
    assert jobs[mine]["origin"] == "operator" and jobs[mine]["grade"] == "yellow"
    assert jobs[mine]["grade_reasons"] == ["записей мало: 3"]
    assert (jobs[theirs[0]]["origin"], jobs[theirs[0]]["grade"]) == ("user", "")
    assert jobs[theirs[0]]["comment"] == "новые правила"
    only_users = (await ops.get("/v1/ops/jobs?origin=user", headers=AUTH)).json()
    assert [j["id"] for j in only_users] == [theirs[0]]
    detail = (await ops.get(f"/v1/ops/jobs/{mine}", headers=AUTH)).json()
    assert detail["grade"] == "yellow"
    assert (await ops.get("/v1/ops/jobs?origin=x", headers=AUTH)).status_code == 422
