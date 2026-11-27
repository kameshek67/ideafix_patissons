"""Страница «Качество данных»: оценка извлечения, покрытие, жалобы, помощник."""

import json
import re
from pathlib import Path

import httpx
import psycopg
import pytest
from olymp_db.session import psycopg_dsn


async def get_quality(client: httpx.AsyncClient) -> dict:
    response = await client.get("/v1/quality")
    assert response.status_code == 200
    return response.json()


async def test_extraction_from_eval_files(client: httpx.AsyncClient) -> None:
    holdout = (await get_quality(client))["extraction"]["holdout"]
    assert holdout["extraction"]["documents"] == 6
    assert holdout["extraction"]["records"] == 543
    assert 0.7 < holdout["extraction"]["recall"] < 0.8
    assert holdout["extraction"]["who"] == 1.0
    assert holdout["old_table"]["recall"] < 0.05
    development = (await get_quality(client))["extraction"]["development"]
    assert development["extraction"]["documents"] == 10
    assert development["extraction"]["precision"] > 0.99


async def test_coverage_and_freshness(client: httpx.AsyncClient) -> None:
    data = await get_quality(client)
    coverage = data["coverage"]
    assert coverage["universities"] == 44
    assert coverage["with_table"] + len(coverage["without_table"]) == 44
    assert coverage["with_table"] > 0
    assert all(item["name"] for item in coverage["without_table"])
    assert coverage["layers"]["detailed"] > 0
    assert "raw" not in coverage["layers"]
    fresh = data["freshness"]
    assert fresh["built_at"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\d", fresh["rsosh_list"])
    assert fresh["documents_checked_from"] <= fresh["documents_checked_to"]


async def test_missing_files_leave_blanks(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLYMP_DATA_DIR", str(tmp_path))
    data = await get_quality(client)
    assert data["extraction"]["holdout"] == {"old_table": None, "extraction": None}
    assert data["extraction"]["development"] == {"old_table": None, "extraction": None}
    assert data["freshness"]["rsosh_list"] is None
    assert data["freshness"]["documents_checked_to"] is None
    assert data["assistant"] is None
    assert data["coverage"]["universities"] == 44


async def test_assistant_summary(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLYMP_DATA_DIR", str(tmp_path))
    (tmp_path / "eval" / "assistant").mkdir(parents=True)
    report = {
        "model": "vendor/model-x",
        "date": "2026-11-27T10:00:00+00:00",
        "summary": {
            "cases": 120,
            "passed_share": 0.93,
            "error_share_final": 0.02,
            "fabrication_final": 0.0,
            "answer_p50": 6.5,
            "cost_per_answer": None,
        },
    }
    path = tmp_path / "eval" / "assistant" / "summary.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assistant = (await get_quality(client))["assistant"]
    assert assistant["model"] == "vendor/model-x"
    assert assistant["date"] == "2026-11-27"
    assert assistant["cases"] == 120 and assistant["passed_share"] == 0.93
    assert assistant["cost_per_answer"] is None
    path.write_text("не json", encoding="utf-8")
    assert (await get_quality(client))["assistant"] is None


async def test_reports_counts_without_texts(
    client: httpx.AsyncClient, built_database_url: str
) -> None:
    before = (await get_quality(client))["reports"]
    insert = """INSERT INTO data_reports
                  (kind, context, message, source, status, quote, created_at, resolved_at)
                VALUES ('program', '{}', 'секретный текст жалобы', 'monitor', %(status)s,
                        %(quote)s, now() - make_interval(hours => %(age)s),
                        now() - make_interval(hours => %(age)s - %(took)s))"""
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        # возраст жалобы и за сколько часов решена
        for status, quote, age, took in (
            ("fixed", "", 24 * 40, 3),
            ("correct", "цитата", 48, 1),
            ("duplicate", "", 24, 1),
            ("new", "", 24, 0),
        ):
            conn.execute(insert, {"status": status, "quote": quote, "age": age, "took": took})
        conn.commit()
    response = await client.get("/v1/quality")
    assert "секретный текст" not in response.text
    after = response.json()["reports"]
    assert after["total"]["received"] - before["total"]["received"] == 3
    assert after["total"]["fixed"] - before["total"]["fixed"] == 1
    assert after["total"]["correct"] - before["total"]["correct"] == 1
    assert after["days_30"]["received"] - before["days_30"]["received"] == 2
    assert after["days_30"]["fixed"] == before["days_30"]["fixed"]
    assert after["days_30"]["correct"] - before["days_30"]["correct"] == 1
    assert after["total"]["median_hours"] is not None
