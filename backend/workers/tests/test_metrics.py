"""olymp_workers.metrics: функции подсчёта на маленьких данных и сверка с сохранёнными отчётами."""

import gzip
import json
from datetime import date
from pathlib import Path

import psycopg
import pytest
from olymp_db.session import psycopg_dsn
from olymp_domain.extraction import ExtractionFile
from olymp_workers import eval_extract as ev
from olymp_workers import metrics as mt
from olymp_workers import metrics_stats as st

from .test_analysis import add_benefit, build
from .test_eval_extract import GOLD, file, rec

RUNS = mt.EVAL_DIR / "assistant" / "runs"


# ---------------------------------------------------------------- статистика


def test_wilson_matches_known_values() -> None:
    low, high = st.wilson(50, 100) or (0, 0)
    assert (round(low, 4), round(high, 4)) == (0.4038, 0.5962)
    low, high = st.wilson(0, 10) or (1, 1)
    assert low == 0 and round(high, 4) == 0.2775
    assert st.wilson(0, 0) is None


def test_wilson_stays_inside_zero_and_one() -> None:
    for k, n in ((0, 3), (3, 3), (1, 1)):
        low, high = st.wilson(k, n) or (-1, 2)
        assert 0 <= low <= k / n <= high <= 1


def test_percentile_is_nearest_rank() -> None:
    values = [5.0, 1.0, 3.0, 2.0, 4.0]
    assert st.percentile(values, 0.5) == 3.0
    assert st.percentile(values, 0.95) == 5.0
    assert st.percentile(values, 0.0) == 1.0
    assert st.percentile([], 0.5) is None


def test_bootstrap_mean_is_repeatable_and_brackets_the_share() -> None:
    flags = [True] * 90 + [False] * 10
    first = st.bootstrap_mean(flags)
    assert first == st.bootstrap_mean(flags)
    assert first is not None and first[0] < 0.9 < first[1]
    assert st.bootstrap_mean([True] * 20) == (1.0, 1.0)
    assert st.bootstrap_mean([]) is None


def test_bootstrap_by_documents_is_wider_than_by_records_when_documents_differ() -> None:
    # (эталон, извлечено, совпало): один документ идеален, второй провален
    clusters = [(100, 100, 100), (100, 100, 20)]
    flags = [True] * 120 + [False] * 80
    by_docs = st.bootstrap_clusters(clusters, lambda t: mt._ratio(t[2], t[1]))
    by_records = st.bootstrap_mean(flags)
    assert by_docs is not None and by_records is not None
    assert by_docs[1] - by_docs[0] > by_records[1] - by_records[0]


def test_bootstrap_by_documents_skips_undefined_samples() -> None:
    assert st.bootstrap_clusters([(0, 0, 0)], lambda t: mt._ratio(t[2], t[1])) is None


# ---------------------------------------------------------------- извлечение


def test_score_json_has_three_kinds_of_interval() -> None:
    pred = file(
        [
            rec("01.03.02", "Высшая проба", winner_role="both", levels=[1]),
            rec("01.03.02", "Ломоносов", winner_role="prizewinner"),
            rec("01.03.02", "Лишняя олимпиада"),
        ]
    )
    results, total = ev.run({"d": GOLD}, {"d": pred})
    out = mt.score_json(total, with_bootstrap=True, documents=results)
    assert (out["gold"], out["pred"], out["matched"]) == (3, 3, 2)
    precision = out["precision"]
    assert precision["value"] == round(2 / 3, 4)
    for key in ("bootstrap_records", "bootstrap_documents"):
        assert precision[key]["low"] <= precision["value"] <= precision[key]["high"]
    assert precision["low"] < precision["value"] < precision["high"]
    assert out["fields"]["winner_role"]["correct"] == 1 and out["fields"]["winner_role"]["of"] == 2
    assert out["role_wrong"]["count"] == 1
    assert set(out["fields"]) == set(ev.FIELDS)


def test_score_json_without_bootstrap_skips_it() -> None:
    results, total = ev.run({"d": GOLD}, {"d": GOLD})
    out = mt.score_json(total, with_bootstrap=False, documents=results)
    assert "bootstrap_records" not in out["precision"]
    assert out["precision"]["value"] == 1.0 and out["recall"]["value"] == 1.0


def test_relabel_gives_predictions_the_gold_university_name() -> None:
    data = file([rec("01.03.02", "МОШ")]).model_dump(mode="json")
    data["document"]["university"] = "Вуз (КФУ)"
    data["records"][0]["university"] = "Вуз (КФУ)"
    gold = ExtractionFile.model_validate(data)
    pred = file([rec("01.03.02", "МОШ")])
    plain = ev.run({"d": gold}, {"d": pred})[1]
    assert plain.matched == 0  # название вуза входит в ключ записи
    fixed = mt.relabel({"p": pred}, {"d": gold})
    assert ev.run({"d": gold}, fixed)[1].matched == 1
    assert mt.relabel({}, {"d": gold}) == {}


def test_document_json_marks_threshold() -> None:
    results, _ = ev.run({"d": GOLD}, {"d": GOLD})
    row = mt.document_json(results[0])
    assert row["document"] == "d" and row["passes"] is True


# ---------------------------------------------------------------- помощник


def turn(**extra: object) -> dict:
    base: dict = {
        "answer": "итог",
        "raw_answer": "итог",
        "seconds": 5.0,
        "failure": None,
        "violations": [],
        "raw_violations": [],
        "expected": {"hits": [], "hits_who": 0, "hits_type": 0},
        "raw_expected": {"hits": [], "hits_who": 0, "hits_type": 0},
    }
    return base | extra


def test_error_kinds_ignore_hedges_and_count_forbidden() -> None:
    t = turn(
        raw_violations=[{"kind": "role"}, {"kind": "hedge"}],
        raw_expected={"hits": ["запрещённое"], "hits_who": 1, "hits_type": 0},
    )
    assert mt.error_kinds(t, raw=True) == {"role", "forbidden"}
    assert mt.error_kinds(t, raw=False) == set()
    assert mt.who_type_error(t, raw=True) and not mt.who_type_error(t, raw=False)
    assert not mt.who_type_error(turn(raw_violations=[{"kind": "number"}]), raw=True)


def test_run_metrics_by_kind_with_intervals() -> None:
    bad = turn(
        answer="исправлен",
        raw_answer="с ошибкой",
        raw_violations=[{"kind": "number"}],
    )
    data = {
        "model": "тест",
        "cases": [
            {"id": "a", "kind": "pair", "passed": True, "turns": [turn(), bad]},
            {"id": "b", "kind": "pair", "passed": False, "turns": [turn(failure="сеть")]},
            {"id": "c", "kind": "hobby", "passed": True, "turns": [turn(seconds=40.0)]},
        ],
    }
    out = mt.run_metrics(data)
    assert out["cases"] == 3 and out["passed"]["count"] == 2
    assert out["answered_turns"] == 3  # реплика с ошибкой сети не считается ответом
    assert out["errors_before"]["count"] == 1 and out["errors_after"]["count"] == 0
    assert out["answers_changed_by_check"]["count"] == 1
    assert (
        out["errors_before"]["low"] < out["errors_before"]["value"] < out["errors_before"]["high"]
    )
    assert out["by_kind"]["pair"]["cases"] == 2 and out["by_kind"]["hobby"]["cases"] == 1
    assert out["by_kind"]["pair"]["errors_before"]["count"] == 1
    assert out["gate_passed"] is False  # p95 = 40 с


def test_run_metrics_gate_passes_when_clean_and_fast() -> None:
    data = {"model": "м", "cases": [{"id": "a", "kind": "x", "passed": True, "turns": [turn()]}]}
    assert mt.run_metrics(data)["gate_passed"] is True


@pytest.mark.skipif(not RUNS.is_dir(), reason="нет сохранённых прогонов")
def test_recomputed_shares_match_saved_summaries() -> None:
    paths = sorted(RUNS.glob("*-rescored.json"))
    assert paths
    for path in paths:
        saved = json.loads(path.read_text(encoding="utf-8"))
        out = mt.run_metrics(saved)
        stats = saved["summary"]
        assert out["cases"] == stats["cases"], path.name
        assert out["passed"]["count"] == stats["passed"], path.name
        assert out["answered_turns"] == stats["answered_turns"], path.name
        assert out["errors_before"]["value"] == pytest.approx(stats["error_share_raw"], abs=1e-3)
        assert out["errors_after"]["value"] == pytest.approx(stats["error_share_final"], abs=1e-3)
        assert out["who_type_errors_before"] == stats["who_type_errors_raw"], path.name
        assert out["who_type_errors_after"] == stats["who_type_errors_final"], path.name
        assert out["answer_p95"] == pytest.approx(stats["answer_p95"], abs=0.01), path.name
        assert out["gate_passed"] == saved["gate"]["passed"], path.name


# ---------------------------------------------------------------- база


def test_mean_age_days_skips_unreadable_dates() -> None:
    age = mt.mean_age_days(["2026-11-18", "2026-11-08", "", "вчера"], date(2026, 11, 28))
    assert age["documents"] == 2 and age["mean_days"] == 15.0
    assert (age["min_days"], age["max_days"]) == (10, 20)
    assert mt.mean_age_days([], date(2026, 11, 28))["mean_days"] is None


def test_rsosh_list_counts_distinct_olympiads(tmp_path: Path) -> None:
    path = tmp_path / "rsosh.json"
    path.write_text(json.dumps({"rows": [{"number": 1}, {"number": 1}, {"number": 2}]}))
    assert mt.rsosh_list_size(path) == 2
    assert mt.rsosh_list_size(tmp_path / "нет.json") is None


def test_rsosh_coverage_counts_olympiads_without_benefits() -> None:
    rows = [
        {"canonical_name": "А", "rows": 3},
        {"canonical_name": "Б", "rows": 0},
    ]
    out = mt.rsosh_coverage(4, rows)  # одной олимпиады перечня в базе нет вообще
    assert out["in_list"] == 4 and out["found_in_database"] == 2
    assert out["with_benefits"]["count"] == 1 and out["with_benefits"]["of"] == 4
    assert out["without_benefits"] == ["Б"]


def test_database_metrics_on_small_database(empty_database_url: str, tmp_path: Path) -> None:
    rsosh = tmp_path / "rsosh.json"
    rsosh.write_text(json.dumps({"rows": [{"number": 1}, {"number": 2}, {"number": 3}]}))
    documents = tmp_path / "docs.json"
    documents.write_text(json.dumps({"Вуз А": {"checked_at": "2026-11-18"}}))
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        try:
            build(conn)
            program = conn.execute("SELECT id FROM programs ORDER BY id LIMIT 1").fetchone()[0]
            listed = conn.execute(
                "SELECT id FROM olympiads WHERE canonical_name = 'Первая'"
            ).fetchone()[0]
            add_benefit(conn, program, listed, "победители", layer="document")
            conn.execute(
                "UPDATE benefits SET source_quote = 'цитата', source_url = 'https://x' "
                "WHERE layer = 'document'"
            )
            out = mt.database_metrics(conn, date(2026, 11, 28), rsosh, documents)
        finally:
            conn.rollback()
    assert (out["universities"], out["programs"], out["olympiads"]) == (2, 2, 3)
    assert out["layers"]["document"]["rows"] == 1
    assert out["layers"]["document"]["with_quote_and_source"]["count"] == 1
    assert out["layers"]["detailed"]["with_quote"]["count"] == 0
    assert out["benefit_rows"] == {"visible": 6, "raw_not_shown": 1}
    assert out["universities_with_document_layer"]["count"] == 1
    assert out["source_check_age"]["mean_days"] == 10.0
    assert out["rsosh_list"]["in_list"] == 3
    assert out["rsosh_list"]["with_benefits"]["count"] == 1
    assert out["check_rows"]["of_bvi_rows"] >= 1


# ---------------------------------------------------------------- API и фронт


def test_latency_percentiles_in_milliseconds() -> None:
    out = mt.latency([0.001 * n for n in range(1, 101)], failed=2)
    assert out["requests"] == 102 and out["failed"] == 2
    assert out["p50_ms"] == 50.0 and out["p95_ms"] == 95.0 and out["max_ms"] == 100.0
    assert mt.latency([], failed=1)["p50_ms"] is None


def test_api_paths_use_ids_from_the_api_itself() -> None:
    answers = {
        "/v1/olympiads?limit=12": {
            "items": [{"id": 7, "canonical_name": "Олимпиада", "short_name": "Олимп"}]
        },
        "/v1/universities": {"items": [{"id": 3}]},
        "/v1/programs?university_id=3&limit=5": {"items": [{"id": 11}]},
        "/v1/achievements/olympiads/7": {
            "olympiad": {"key": "олимп"},
            "profiles": [{"key": "математика"}],
        },
    }
    paths = mt.api_paths(lambda path: answers[path])
    assert paths["GET /v1/olympiads/{id}/profiles"] == ["/v1/olympiads/7/profiles"]
    assert paths["GET /v1/search/by-program (карточка программы)"] == [
        "/v1/search/by-program?program_id=11"
    ]
    (match,) = paths["GET /v1/achievements/match"]
    assert "diploma=%D0%BE%D0%BB%D0%B8%D0%BC%D0%BF.%D0%BC" in match and match.endswith("w.11.2025")
    assert all(urls for urls in paths.values())


def test_api_metrics_refuses_more_than_the_cap() -> None:
    with pytest.raises(ValueError):
        mt.api_metrics("http://127.0.0.1:1", requests=mt.MAX_REQUESTS + 1)


def test_first_load_js_sums_scripts_from_the_page(tmp_path: Path) -> None:
    chunks = tmp_path / "static" / "chunks"
    chunks.mkdir(parents=True)
    body = b"console.log('x');" * 500
    for name in ("a.js", "b.js", "lazy.js"):
        (chunks / name).write_bytes(body)
    app = tmp_path / "server" / "app"
    app.mkdir(parents=True)
    (app / "index.html").write_text(
        '<link rel="preload" href="/_next/static/chunks/lazy.js" as="script"/>'
        '<script src="/_next/static/chunks/a.js?dpl=1" async=""></script>'
        '<script src="/_next/static/chunks/b.js"></script>'
        '<script src="/_next/static/chunks/a.js"></script>'
    )
    out = mt.first_load_js(tmp_path)
    assert out["scripts"] == 2  # повтор и preload без выполнения не считаются
    assert out["raw_kb"] == round(2 * len(body) / 1024, 1)
    assert out["gzip_kb"] == round(2 * len(gzip.compress(body, 6)) / 1024, 1)


def test_test_counters_parse_tool_output() -> None:
    assert mt.pytest_count("a::b\n\n949 tests collected in 2.02s\n") == 949
    assert mt.pytest_count("1 test collected") == 1
    assert mt.pytest_count("ошибка") is None
    out = 'шум\n{"numTotalTests": 5, "numPassedTests": 4, "numFailedTests": 1}'
    assert mt.vitest_count(out) == {"total": 5, "passed": 4, "failed": 1}
    assert mt.vitest_count("нет json") is None
