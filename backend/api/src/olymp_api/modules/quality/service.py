"""Страница «Качество данных»: оценка извлечения, покрытие базы, жалобы, помощник.

Файлы оценки лежат в data/eval/** (их кладут сравнения и прогоны), их может не быть:
тогда соответствующая часть пустая, остальное считается как обычно.
"""

import json
from pathlib import Path
from typing import Any

from olymp_domain.admission_rules import data_dir
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import fetch_all, fetch_one

RSOSH_FILE = "rsosh_2026_27.json"
DOCUMENTS_FILE = "university_documents.json"


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def extraction_score(path: Path) -> dict[str, Any] | None:
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("total"), dict):
        return None
    total = data["total"]
    precision, recall = number(total.get("precision")), number(total.get("recall"))
    records = total.get("gold")
    if precision is None or recall is None or not isinstance(records, int):
        return None
    fields = total.get("fields")
    documents = data.get("documents")
    return {
        "documents": len(documents) if isinstance(documents, list) else 0,
        "records": records,
        "precision": precision,
        "recall": recall,
        "who": number(fields.get("winner_role")) if isinstance(fields, dict) else None,
    }


def extraction() -> dict[str, Any]:
    eval_dir = data_dir() / "eval"
    return {
        name: {
            "old_table": extraction_score(eval_dir / folder / "baseline-xlsx.json"),
            "extraction": extraction_score(eval_dir / folder / "baseline-extract.json"),
        }
        for name, folder in (("development", "extraction"), ("holdout", "holdout"))
    }


def date_part(value: Any) -> str | None:
    return value[:10] if isinstance(value, str) and value else None


def file_dates() -> dict[str, str | None]:
    rsosh = read_json(data_dir() / RSOSH_FILE)
    documents = read_json(data_dir() / DOCUMENTS_FILE)
    checked = sorted(
        d
        for v in (documents.values() if isinstance(documents, dict) else ())
        if isinstance(v, dict) and (d := date_part(v.get("checked_at")))
    )
    return {
        "rsosh_list": date_part(rsosh.get("fetched_at")) if isinstance(rsosh, dict) else None,
        "documents_checked_from": checked[0] if checked else None,
        "documents_checked_to": checked[-1] if checked else None,
    }


async def coverage(session: AsyncSession) -> dict[str, Any]:
    universities = await fetch_all(
        session,
        """SELECT u.id, u.name,
                  -- таблица льгот — любой слой, кроме текстовых правил и исходного перечисления
                  EXISTS (SELECT 1 FROM programs p JOIN benefits b ON b.program_id = p.id
                          WHERE p.university_id = u.id AND b.layer NOT IN ('summary', 'raw')) AS has_table
           FROM universities u ORDER BY u.name""",
    )
    layers = await fetch_all(
        session, "SELECT layer, COUNT(*) AS rows FROM benefits WHERE layer <> 'raw' GROUP BY layer"
    )
    return {
        "universities": len(universities),
        "with_table": sum(u["has_table"] for u in universities),
        "without_table": [
            {"id": u["id"], "name": u["name"]} for u in universities if not u["has_table"]
        ],
        "layers": {r["layer"]: r["rows"] for r in sorted(layers, key=lambda r: r["layer"])},
    }


async def reports(session: AsyncSession) -> dict[str, Any]:
    """Жалобы без текстов. Дубликаты не считаем: это та же жалоба, поданная ещё раз."""
    row = await fetch_one(
        session,
        """SELECT
             count(*) AS total_received,
             count(*) FILTER (WHERE status = 'fixed') AS total_fixed,
             count(*) FILTER (WHERE status = 'correct') AS total_correct,
             percentile_cont(0.5) WITHIN GROUP (
               ORDER BY extract(epoch FROM resolved_at - created_at) / 3600
             ) FILTER (WHERE status IN ('fixed', 'correct')) AS total_median,
             count(*) FILTER (WHERE recent) AS days_received,
             count(*) FILTER (WHERE recent AND status = 'fixed') AS days_fixed,
             count(*) FILTER (WHERE recent AND status = 'correct') AS days_correct,
             percentile_cont(0.5) WITHIN GROUP (
               ORDER BY extract(epoch FROM resolved_at - created_at) / 3600
             ) FILTER (WHERE recent AND status IN ('fixed', 'correct')) AS days_median
           FROM (SELECT status, created_at, resolved_at,
                        created_at >= now() - interval '30 days' AS recent
                 FROM data_reports WHERE status <> 'duplicate') r""",
    )
    assert row is not None

    def period(prefix: str) -> dict[str, Any]:
        median = row[f"{prefix}_median"]
        return {
            "received": row[f"{prefix}_received"],
            "fixed": row[f"{prefix}_fixed"],
            "correct": row[f"{prefix}_correct"],
            "median_hours": round(float(median), 1) if median is not None else None,
        }

    return {"total": period("total"), "days_30": period("days")}


def compared_models(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Строки сравнения моделей из summary.json; кривые записи пропускаем."""
    rows = []
    for item in data.get("models") or []:
        if not isinstance(item, dict) or not isinstance(item.get("model"), str):
            continue
        cases, gate = item.get("cases"), item.get("gate_passed")
        rows.append(
            {
                "model": item["model"],
                "cases": cases if isinstance(cases, int) else None,
                "passed_share": number(item.get("passed_share")),
                "error_share_raw": number(item.get("error_share_raw")),
                "error_share_final": number(item.get("error_share_final")),
                "answer_p95": number(item.get("answer_p95")),
                "cost_per_answer": number(item.get("cost_per_answer")),
                "gate_passed": gate if isinstance(gate, bool) else None,
            }
        )
    return rows


def assistant() -> dict[str, Any] | None:
    """Выбранная модель и её метрики из data/eval/assistant/summary.json; нет файла — None."""
    data = read_json(data_dir() / "eval" / "assistant" / "summary.json")
    if not isinstance(data, dict):
        return None
    chosen = data.get("selected") or data.get("model")
    if isinstance(chosen, dict):
        data, chosen = {**data, **chosen}, chosen.get("model")
    if not isinstance(chosen, str) or not chosen:
        return None
    stats = data.get("summary") or data.get("metrics")
    if not isinstance(stats, dict):
        return None
    cases = stats.get("cases")
    return {
        "model": chosen,
        "date": date_part(data.get("date")),
        "cases": cases if isinstance(cases, int) else None,
        "passed_share": number(stats.get("passed_share")),
        "error_share": number(stats.get("error_share_final")),
        "fabrication": number(stats.get("fabrication_final")),
        "answer_p50": number(stats.get("answer_p50")),
        "cost_per_answer": number(stats.get("cost_per_answer")),
        "models": compared_models(data),
    }


async def quality(session: AsyncSession) -> dict[str, Any]:
    built = await fetch_one(session, "SELECT value FROM meta WHERE key = 'built_at'")
    return {
        "extraction": extraction(),
        "coverage": await coverage(session),
        "freshness": {"built_at": built["value"] if built else None, **file_dates()},
        "reports": await reports(session),
        "assistant": assistant(),
    }
