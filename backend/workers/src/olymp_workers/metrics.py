"""Все метрики, которые считаются без людей: data/eval/metrics.json.

    olymp-metrics                          # всё сразу
    olymp-metrics --only extraction,assistant
    olymp-metrics --api http://127.0.0.1:18000 --requests 150

Разделы:
  extraction — точность и полнота извлечения с интервалами, по документам и по полям;
  assistant  — интервалы по сохранённым прогонам помощника (модель не вызывается);
  database   — размер базы, слои, цитаты и источники, покрытие перечня РСОШ (нужна база);
  api        — задержки GET-эндпоинтов локального демо (нужен запущенный API);
  frontend   — размер JS главной из frontend/.next, число тестов фронта и бэка.
Раздел, которому не хватило окружения, получает {"error": "..."} — остальные считаются.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from olymp_domain.extraction import ExtractionFile, load_dir

from .eval_extract import FIELDS, DocResult, find_pred, run
from .ingest import DATA_DIR, REPO
from .metrics_stats import (
    bootstrap_clusters,
    bootstrap_mean,
    interval_json,
    percentile,
    share,
    wilson,
)

EVAL_DIR = DATA_DIR / "eval"
OUT = EVAL_DIR / "metrics.json"
SECTIONS = ("extraction", "assistant", "database", "api", "frontend")
FIELD_TITLES = {
    "winner_role": "кому",
    "levels": "уровень",
    "grades": "класс",
    "ege_min": "порог ЕГЭ",
    "ege_subjects": "предмет ЕГЭ",
}
MAX_REQUESTS = 300  # потолок на один эндпоинт: мы мерим скорость, а не нагружаем


# ---------------------------------------------------------------- 1. извлечение


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def score_json(
    result: DocResult, *, with_bootstrap: bool, documents: list[DocResult]
) -> dict[str, Any]:
    """Точность, полнота и поля одного набора документов с интервалами."""
    precision, recall = result.precision, result.recall
    out: dict[str, Any] = {
        "gold": result.gold,
        "pred": result.pred,
        "matched": result.matched,
        "precision": {
            **interval_json(precision, wilson(result.matched, result.pred)),
            "interval": "wilson",
        },
        "recall": {
            **interval_json(recall, wilson(result.matched, result.gold)),
            "interval": "wilson",
        },
    }
    if with_bootstrap:
        clusters = [(d.gold, d.pred, d.matched) for d in documents]
        out["precision"]["bootstrap_records"] = interval_json(
            precision, bootstrap_mean(result.pred_hits)
        )
        out["recall"]["bootstrap_records"] = interval_json(recall, bootstrap_mean(result.gold_hits))
        out["precision"]["bootstrap_documents"] = interval_json(
            precision, bootstrap_clusters(clusters, lambda t: _ratio(t[2], t[1]))
        )
        out["recall"]["bootstrap_documents"] = interval_json(
            recall, bootstrap_clusters(clusters, lambda t: _ratio(t[2], t[0]))
        )
    out["fields"] = {
        name: {
            "title": FIELD_TITLES[name],
            **interval_json(
                result.field_accuracy(name), wilson(result.field_ok[name], result.matched)
            ),
            "correct": result.field_ok[name],
            "of": result.matched,
        }
        for name in FIELDS
    }
    out["role_wrong"] = {
        "count": result.role_wrong,
        "of": result.matched,
        **interval_json(
            _ratio(result.role_wrong, result.matched), wilson(result.role_wrong, result.matched)
        ),
    }
    return out


def document_json(result: DocResult) -> dict[str, Any]:
    return {
        "document": result.name,
        "university": result.university,
        **score_json(result, with_bootstrap=False, documents=[]),
        "passes": result.passes,
        "note": result.note,
    }


def relabel(
    pred: dict[str, ExtractionFile], gold: dict[str, ExtractionFile]
) -> dict[str, ExtractionFile]:
    """Предсказания под названиями вузов эталона: документ тот же, а вуз в файлах назван иначе.

    Запись сопоставляется по ключу с названием вуза, и «КФУ» в скобках не должно стоить совпадения."""
    out: dict[str, ExtractionFile] = {}
    for name, gold_file in gold.items():
        found = find_pred(name, gold_file, pred)
        if found is None:
            continue
        data = found.model_dump(mode="json")
        university = gold_file.document.university
        data["document"]["university"] = university
        for record in data["records"]:
            record["university"] = university
        out[name] = ExtractionFile.model_validate(data)
    return out


def extraction_metrics(
    eval_dir: Path,
    extracted_dir: Path,
    old_conn: Any = None,
    *,
    resamples: bool = True,
) -> dict[str, Any]:
    """Метрики на наборе настройки и отложенном: извлечение из документов и старая таблица.

    Старая таблица — база, собранная из одного XLSX без слоя document (old_conn)."""
    pred_files = load_dir(extracted_dir)
    sets = {"development": eval_dir / "extraction", "holdout": eval_dir / "holdout"}
    out: dict[str, Any] = {}
    for set_name, gold_dir in sets.items():
        gold = load_dir(gold_dir)
        runs = {"extract": run(gold, relabel(pred_files, gold))}
        if old_conn is not None:
            runs["old_table"] = run(gold, None, conn=old_conn)
        out[set_name] = {
            "documents_in_set": len(gold),
            **{
                source: {
                    "total": score_json(total, with_bootstrap=resamples, documents=results),
                    "documents": [document_json(r) for r in results],
                }
                for source, (results, total) in runs.items()
            },
        }
    return out


# ---------------------------------------------------------------- 2. помощник

ERROR_KINDS = frozenset({"entity", "number", "role", "benefit_type", "threshold", "not_listed"})
GATE_ERRORS = 0.05
GATE_SECONDS = 20


def error_kinds(turn: dict[str, Any], raw: bool) -> set[str]:
    """Виды фактических ошибок реплики: нарушения проверки фактов и сработавшие запреты набора."""
    problems = turn.get("raw_violations" if raw else "violations") or []
    found = {str(v.get("kind")) for v in problems} & ERROR_KINDS
    expected = turn.get("raw_expected" if raw else "expected") or {}
    if expected.get("hits"):
        found.add("forbidden")
    return found


def who_type_error(turn: dict[str, Any], raw: bool) -> bool:
    """Ошибка «кому» или «тип льготы»."""
    problems = turn.get("raw_violations" if raw else "violations") or []
    expected = turn.get("raw_expected" if raw else "expected") or {}
    kinds = {v.get("kind") for v in problems}
    return bool(
        kinds & {"role", "benefit_type"} or expected.get("hits_who") or expected.get("hits_type")
    )


def count_json(part: int, whole: int) -> dict[str, Any]:
    return {"count": part, "of": whole, **interval_json(share(part, whole), wilson(part, whole))}


def run_metrics(data: dict[str, Any]) -> dict[str, Any]:
    """Метрики одного прогона помощника с интервалами Уилсона, в целом и по типам вопросов."""
    cases = data["cases"]

    def block(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
        turns = [t for c in items for t in c["turns"] if not t.get("failure")]
        changed = sum(1 for t in turns if t.get("answer") != t.get("raw_answer"))
        return {
            "cases": len(items),
            "passed": count_json(sum(1 for c in items if c["passed"]), len(items)),
            "answered_turns": len(turns),
            "errors_before": count_json(sum(bool(error_kinds(t, True)) for t in turns), len(turns)),
            "errors_after": count_json(sum(bool(error_kinds(t, False)) for t in turns), len(turns)),
            "who_type_errors_before": sum(who_type_error(t, True) for t in turns),
            "who_type_errors_after": sum(who_type_error(t, False) for t in turns),
            # без проверки фактов школьник увидел бы сырой ответ: сколько ответов она меняет
            "answers_changed_by_check": count_json(changed, len(turns)),
        }

    turns = [t for c in cases for t in c["turns"] if not t.get("failure")]
    seconds = [float(t["seconds"]) for t in turns if t.get("seconds") is not None]
    whole = block(cases)
    after = whole["errors_after"]
    p95 = percentile(seconds, 0.95)
    whole["answer_p50"] = _round(percentile(seconds, 0.5))
    whole["answer_p95"] = _round(p95)
    whole["gate_passed"] = bool(
        whole["who_type_errors_after"] == 0
        and after["value"] is not None
        and after["value"] <= GATE_ERRORS
        and p95 is not None
        and p95 < GATE_SECONDS
    )
    kinds: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        kinds.setdefault(case.get("kind") or "", []).append(case)
    return {
        "model": data["model"],
        "date": data.get("date"),
        **whole,
        "by_kind": {k: block(v) for k, v in sorted(kinds.items())},
    }


def assistant_metrics(runs_dir: Path) -> dict[str, Any]:
    runs = []
    for path in sorted(runs_dir.glob("*-rescored.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        runs.append({"file": path.name, **run_metrics(data)})
    return {"runs": runs}


# ---------------------------------------------------------------- 3. база

LAYERS_SQL = """
SELECT layer,
       count(*) AS rows,
       count(*) FILTER (WHERE source_quote <> '') AS with_quote,
       count(*) FILTER (WHERE source_url <> '') AS with_source,
       count(*) FILTER (WHERE source_quote <> '' AND source_url <> '') AS with_both
FROM benefits GROUP BY layer ORDER BY layer
"""
RSOSH_SQL = """
SELECT o.id, o.canonical_name,
       count(DISTINCT b.id) AS rows,
       count(DISTINCT p.university_id) AS universities
FROM olympiads o
LEFT JOIN benefit_olympiads bo ON bo.olympiad_id = o.id
LEFT JOIN benefits b ON b.id = bo.benefit_id AND b.layer <> 'raw'
LEFT JOIN programs p ON p.id = b.program_id
WHERE o.in_rsosh_2026_27
GROUP BY o.id, o.canonical_name
ORDER BY o.canonical_name
"""


def mean_age_days(dates: Iterable[str], today: date) -> dict[str, Any]:
    """Возраст проверки источников в днях на дату today; нечитаемые даты не считаются."""
    ages = []
    for text in dates:
        try:
            ages.append((today - datetime.strptime(text[:10], "%Y-%m-%d").date()).days)
        except ValueError:
            continue
    return {
        "as_of": today.isoformat(),
        "documents": len(ages),
        "mean_days": _round(sum(ages) / len(ages), 1) if ages else None,
        "min_days": min(ages, default=None),
        "max_days": max(ages, default=None),
    }


def rsosh_list_size(path: Path) -> int | None:
    """Сколько разных олимпиад в перечне РСОШ (у олимпиады несколько профилей-строк)."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    except (OSError, ValueError, KeyError):
        return None
    return len({row["number"] for row in rows})


def rsosh_coverage(listed: int | None, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Покрытие перечня: олимпиады перечня, у которых в базе есть хоть одна льгота."""
    covered = [r for r in rows if r["rows"] > 0]
    total = listed if listed is not None else len(rows)
    return {
        "in_list": total,
        "found_in_database": len(rows),
        "with_benefits": count_json(len(covered), total),
        "without_benefits": [r["canonical_name"] for r in rows if r["rows"] == 0],
    }


def database_metrics(
    conn: Any, today: date, rsosh_file: Path, documents_file: Path
) -> dict[str, Any]:
    from psycopg.rows import dict_row

    from .analysis import load_links, prize_2027

    def one(sql: str) -> Any:
        return conn.execute(sql).fetchone()[0]

    with conn.cursor(row_factory=dict_row) as cur:
        layers = list(cur.execute(LAYERS_SQL).fetchall())
        rsosh = list(cur.execute(RSOSH_SQL).fetchall())
    visible = [x for x in layers if x["layer"] != "raw"]

    def layer_json(item: dict[str, Any]) -> dict[str, Any]:
        n = item["rows"]
        return {
            "rows": n,
            "with_quote": count_json(item["with_quote"], n),
            "with_source": count_json(item["with_source"], n),
            "with_quote_and_source": count_json(item["with_both"], n),
        }

    total = {
        k: sum(x[k] for x in visible) for k in ("rows", "with_quote", "with_source", "with_both")
    }
    universities = one("SELECT count(*) FROM universities")
    with_document = one(
        """SELECT count(DISTINCT p.university_id) FROM benefits b
           JOIN programs p ON p.id = b.program_id WHERE b.layer = 'document'"""
    )
    with_table = one(
        """SELECT count(DISTINCT p.university_id) FROM benefits b
           JOIN programs p ON p.id = b.program_id WHERE b.layer NOT IN ('summary', 'raw')"""
    )
    try:
        checked = [
            v.get("checked_at") or ""
            for v in json.loads(documents_file.read_text(encoding="utf-8")).values()
        ]
    except (OSError, ValueError):
        checked = [r[0] for r in conn.execute("SELECT checked_at FROM university_documents")]
    prize = prize_2027(load_links(conn))
    return {
        "universities": universities,
        "programs": one("SELECT count(*) FROM programs"),
        "olympiads": one("SELECT count(*) FROM olympiads"),
        "benefit_rows": {
            "visible": total["rows"],
            "raw_not_shown": next((x["rows"] for x in layers if x["layer"] == "raw"), 0),
        },
        "layers": {x["layer"]: layer_json(x) for x in layers},
        "visible_rows": layer_json({**total, "rows": total["rows"]}),
        "universities_with_table": count_json(with_table, universities),
        "universities_with_document_layer": count_json(with_document, universities),
        "source_check_age": mean_age_days(checked, today),
        "rsosh_list": rsosh_coverage(rsosh_list_size(rsosh_file), rsosh),
        "check_rows": {
            "count": prize["check_rows"],
            "of_bvi_rows": prize["bvi_rows"],
            "role_unstated_rows": prize["role_unstated_rows"],
        },
    }


# ---------------------------------------------------------------- 4. скорость API


def latency(seconds: Sequence[float], failed: int = 0) -> dict[str, Any]:
    """p50, p95 и максимум в миллисекундах по успешным запросам."""
    ms = [s * 1000 for s in seconds]
    return {
        "requests": len(ms) + failed,
        "failed": failed,
        "p50_ms": _round(percentile(ms, 0.5), 1),
        "p95_ms": _round(percentile(ms, 0.95), 1),
        "max_ms": _round(max(ms), 1) if ms else None,
    }


def _q(**params: Any) -> str:
    return "&".join(f"{k}={quote(str(v))}" for k, v in params.items() if v is not None)


def api_paths(get: Callable[[str], Any]) -> dict[str, list[str]]:
    """Адреса основных GET-эндпоинтов: по несколько разных, чтобы не мерить один кэш."""
    olympiads = get("/v1/olympiads?limit=12")["items"]
    unis = get("/v1/universities")["items"]
    programs: list[int] = []
    for uni in unis[:6]:
        items = get(f"/v1/programs?{_q(university_id=uni['id'], limit=5)}")
        programs += [p["id"] for p in (items["items"] if isinstance(items, dict) else items)][:4]
    ids = [o["id"] for o in olympiads]
    diplomas = []
    for oid in ids[:4]:
        card = get(f"/v1/achievements/olympiads/{oid}")
        if card["profiles"]:
            diplomas.append(f"{card['olympiad']['key']}.{card['profiles'][0]['key']}.w.11.2025")
    return {
        "GET /v1/stats": ["/v1/stats"],
        "GET /v1/quality": ["/v1/quality"],
        "GET /v1/regions": ["/v1/regions"],
        "GET /v1/universities": ["/v1/universities"],
        "GET /v1/olympiads": [
            f"/v1/olympiads?{_q(limit=50)}",
            f"/v1/olympiads?{_q(featured='true')}",
        ],
        "GET /v1/olympiads/{id}/profiles": [f"/v1/olympiads/{i}/profiles" for i in ids],
        "GET /v1/programs": [
            f"/v1/programs?{_q(university_id=u['id'], limit=50)}" for u in unis[:12]
        ],
        "GET /v1/search/by-olympiad (карточка олимпиады)": [
            f"/v1/search/by-olympiad?{_q(q=o['short_name'] or o['canonical_name'], olympiad_id=o['id'], view='summary')}"
            for o in olympiads
        ],
        "GET /v1/search/by-olympiad (все строки)": [
            f"/v1/search/by-olympiad?{_q(q=o['short_name'] or o['canonical_name'], olympiad_id=o['id'])}"
            for o in olympiads
        ],
        "GET /v1/search/by-program (карточка программы)": [
            f"/v1/search/by-program?program_id={p}" for p in programs
        ],
        "GET /v1/achievements/olympiads/{id}": [f"/v1/achievements/olympiads/{i}" for i in ids],
        "GET /v1/achievements/match": [f"/v1/achievements/match?{_q(diploma=d)}" for d in diplomas],
        "GET /v1/goals/olympiads": [f"/v1/goals/olympiads?{_q(program_id=p)}" for p in programs],
        "GET /v1/extra-points/universities": ["/v1/extra-points/universities?admission_year=2026"],
    }


def api_metrics(base: str, requests: int = 100, warmup: int = 3) -> dict[str, Any]:
    """Последовательные GET без параллелизма; первые warmup запросов на эндпоинт не учитываются."""
    import httpx

    if requests > MAX_REQUESTS:
        raise ValueError(f"не больше {MAX_REQUESTS} запросов на эндпоинт")
    with httpx.Client(base_url=base, timeout=60) as client:

        def get(path: str) -> Any:
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        paths = api_paths(get)
        result: dict[str, Any] = {}
        for name, urls in paths.items():
            if not urls:
                result[name] = {"error": "нет адресов для проверки"}
                continue
            seconds: list[float] = []
            failed = limited = 0
            sizes: list[int] = []
            for i in range(warmup + requests):
                url = urls[i % len(urls)]
                while True:
                    started = time.perf_counter()
                    try:
                        response = client.get(url)
                    except httpx.HTTPError:
                        response = None
                    spent = time.perf_counter() - started
                    if response is not None and response.status_code == 429:
                        # лимит запросов демо: ждём окно и повторяем, а не давим дальше
                        limited += 1
                        time.sleep(min(float(response.headers.get("retry-after", 10)) + 0.5, 70))
                        continue
                    break
                if i < warmup:
                    continue
                if response is not None and response.status_code == 200:
                    seconds.append(spent)
                    sizes.append(len(response.content))
                else:
                    failed += 1
            result[name] = {
                **latency(seconds, failed),
                "rate_limited_waits": limited,
                "distinct_urls": min(len(urls), warmup + requests),
                "response_kb": _round(sum(sizes) / len(sizes) / 1024, 1) if sizes else None,
            }
    return {"base": base, "requests_per_endpoint": requests, "warmup": warmup, "endpoints": result}


# ---------------------------------------------------------------- 5. фронт и тесты

SCRIPT_SRC = re.compile(r"<script[^>]+\bsrc=\"(/_next/[^\"]+\.js)[^\"]*\"")


def first_load_js(next_dir: Path, page: str = "index.html") -> dict[str, Any]:
    """JS, который браузер скачивает на первой загрузке страницы: скрипты из её HTML (сборка Next)."""
    html = (next_dir / "server" / "app" / page).read_text(encoding="utf-8")
    sources = list(dict.fromkeys(SCRIPT_SRC.findall(html)))
    raw = packed = 0
    for src in sources:
        data = (next_dir / src.removeprefix("/_next/")).read_bytes()
        raw += len(data)
        packed += len(gzip.compress(data, 6))
    return {
        "page": "/" if page == "index.html" else page,
        "scripts": len(sources),
        "raw_kb": round(raw / 1024, 1),
        "gzip_kb": round(packed / 1024, 1),
    }


def pytest_count(output: str) -> int | None:
    match = re.search(r"(\d+) tests? collected", output)
    return int(match.group(1)) if match else None


def vitest_count(output: str) -> dict[str, int] | None:
    start = output.find("{")
    if start < 0:
        return None
    try:
        data = json.loads(output[start:])
    except ValueError:
        return None
    return {
        "total": data["numTotalTests"],
        "passed": data["numPassedTests"],
        "failed": data["numFailedTests"],
    }


def frontend_metrics(repo: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        out["first_load_js"] = first_load_js(repo / "frontend" / ".next")
    except (OSError, ValueError) as exc:
        out["first_load_js"] = {"error": f"нет сборки frontend/.next (npm run build): {exc}"}
    tests: dict[str, Any] = {}
    backend = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=repo / "backend",
        capture_output=True,
        text=True,
        check=False,
    )
    tests["backend_pytest"] = pytest_count(backend.stdout)
    front = subprocess.run(
        ["npx", "vitest", "run", "--reporter=json"],
        cwd=repo / "frontend",
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "NODE_OPTIONS": "--no-experimental-webstorage"},
    )
    tests["frontend_vitest"] = vitest_count(front.stdout)
    out["tests"] = tests
    return out


# ---------------------------------------------------------------- запуск


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="olymp-metrics", description=__doc__.split("\n")[0])
    ap.add_argument("--only", default=",".join(SECTIONS), help="разделы через запятую")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--eval-dir", type=Path, default=EVAL_DIR)
    ap.add_argument("--extracted", type=Path, default=DATA_DIR / "extracted")
    ap.add_argument("--db-url", help="по умолчанию OLYMP_DATABASE_URL")
    ap.add_argument(
        "--old-db-url",
        help="база из одного XLSX без слоя document (как для olymp-analysis): старая таблица",
    )
    ap.add_argument("--api", default="http://127.0.0.1:18000", help="локальное демо для замеров")
    ap.add_argument(
        "--requests", type=int, default=100, help=f"запросов на эндпоинт, до {MAX_REQUESTS}"
    )
    ap.add_argument(
        "--as-of", type=date.fromisoformat, default=None, help="дата для возраста проверок"
    )
    ap.add_argument("--no-bootstrap", action="store_true", help="без бутстрепа (быстрее)")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    wanted = [s.strip() for s in args.only.split(",") if s.strip()]
    unknown = sorted(set(wanted) - set(SECTIONS))
    if unknown:
        print(f"Неизвестные разделы: {', '.join(unknown)}", file=sys.stderr)
        return 2
    today = args.as_of or date.today()
    result: dict[str, Any] = {}
    # результат прошлого запуска сохраняем: --only пересчитывает только названные разделы
    if args.out.exists():
        try:
            result = json.loads(args.out.read_text(encoding="utf-8"))
        except ValueError:
            result = {}

    conn = old_conn = None
    if "extraction" in wanted and not args.old_db_url:
        print("Без --old-db-url нет строк «старая таблица» в разделе extraction.", file=sys.stderr)
    if "extraction" in wanted and args.old_db_url:
        import psycopg
        from olymp_db.session import psycopg_dsn

        old_conn = psycopg.connect(psycopg_dsn(args.old_db_url))
    if "database" in wanted:
        try:
            import psycopg
            from olymp_db.session import psycopg_dsn

            conn = psycopg.connect(psycopg_dsn(args.db_url))
        except Exception as exc:  # noqa: BLE001 — без базы считаем то, что можно
            print(f"Нет базы, разделы с базой урезаны: {exc}", file=sys.stderr)
    try:
        for name in wanted:
            started = time.perf_counter()
            try:
                if name == "extraction":
                    result[name] = extraction_metrics(
                        args.eval_dir, args.extracted, old_conn, resamples=not args.no_bootstrap
                    )
                elif name == "assistant":
                    result[name] = assistant_metrics(args.eval_dir / "assistant" / "runs")
                elif name == "database":
                    if conn is None:
                        raise RuntimeError("нужна база (OLYMP_DATABASE_URL)")
                    result[name] = database_metrics(
                        conn,
                        today,
                        DATA_DIR / "rsosh_2026_27.json",
                        DATA_DIR / "university_documents.json",
                    )
                elif name == "api":
                    result[name] = api_metrics(args.api, args.requests)
                else:
                    result[name] = frontend_metrics(REPO)
            except Exception as exc:  # noqa: BLE001 — раздел не должен ронять остальные
                result[name] = {"error": f"{type(exc).__name__}: {exc}"}
                print(f"{name}: {exc}", file=sys.stderr)
            print(f"{name}: {time.perf_counter() - started:.1f} с")
    finally:
        for opened in (conn, old_conn):
            if opened is not None:
                opened.close()
    result["computed_at"] = datetime.now().isoformat(timespec="seconds")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Метрики: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
