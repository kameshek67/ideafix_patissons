"""Пересчёт сохранённых прогонов помощника без вызова модели."""

import json
from pathlib import Path

import pytest
from olymp_api.llm import TextDelta, Usage
from olymp_api.llm.fake import FakeProvider
from olymp_api.modules.assistant import evaluate, rescore
from olymp_api.modules.assistant.factcheck import Entity, Vocabulary
from olymp_api.modules.quality import service as quality

FACT = {
    "data": "present",
    "facts": [
        {
            "universities": ["НИУ ВШЭ (Москва)"],
            "olympiads": ["«Высшая проба»"],
            "benefit": "БВИ",
            "who": "winners",
        }
    ],
}


@pytest.fixture
def vocab() -> Vocabulary:
    result = Vocabulary()
    result.add_university(1, "НИУ ВШЭ (Москва)", "НИУ ВШЭ (Москва)")
    result.add(Entity("olympiad", 10, "«Высшая проба»"), "«Высшая проба»", "высшая проба")
    return result


async def test_rescore_recounts_expectations_and_model_errors(
    tmp_path: Path, vocab: Vocabulary, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases_file = tmp_path / "cases.jsonl"
    rows = [
        {"id": "a", "question": "Что даёт Высшую пробу в ВШЭ?", "expect": FACT},
        {"id": "b", "question": "Что даёт Высшую пробу в ВШЭ?", "expect": FACT},
    ]
    cases_file.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    cases = evaluate.load_cases(cases_file)
    markup = '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="benefit_conditions">'
    outcomes = [
        await evaluate.run_case(
            cases[0], FakeProvider([[TextDelta("Есть БВИ."), Usage(100, 10, 0.5)]]), None, vocab
        ),
        await evaluate.run_case(
            cases[1],
            FakeProvider([[TextDelta(markup)], [TextDelta(markup), Usage(100, 10, 0.5)]]),
            None,
            vocab,
        ),
    ]
    saved = evaluate.report(outcomes, "fake", cases_file=str(cases_file))
    saved["cases"][0]["turns"][0]["answer"] = (
        "- «Высшая проба» в НИУ ВШЭ (Москва):\n  БВИ\n  Кому: победители"
    )
    saved["cases"][1]["turns"][0].pop("model_error")
    path = tmp_path / "report.json"
    path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")

    out = tmp_path / "report-rescored.json"
    fresh = rescore.rescore_file(path, out)

    first = fresh["cases"][0]["turns"][0]
    second = fresh["cases"][1]["turns"][0]
    assert first["expected"]["found"] == [True]
    assert fresh["cases"][0]["passed"]
    assert second["model_error"]
    assert second["answer"] == "Не получилось ответить, попробуй переформулировать"
    assert "ошибка модели" in fresh["cases"][1]["reasons"][0]
    assert fresh["summary"]["model_errors"] == 1
    assert (fresh["summary"]["passed"], fresh["summary"]["cases"]) == (1, 2)

    summary_path = tmp_path / "eval" / "assistant" / "summary.json"
    summary_path.parent.mkdir(parents=True)
    data = rescore.quality_summary([out])
    summary_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("OLYMP_DATA_DIR", str(tmp_path))
    shown = quality.assistant()
    assert shown is not None and shown["model"] == data["selected"]
    assert shown["cases"] == 2 and shown["passed_share"] == fresh["summary"]["passed_share"]


def test_quality_summary_without_gate_winner(tmp_path: Path) -> None:
    saved = {
        "date": "2026-11-26T14:00:00+00:00",
        "model": "model-a",
        "provider": "https://proxy.example",
        "summary": {
            "cases": 5,
            "passed_share": 0.2,
            "error_share_raw": 0.4,
            "error_share_final": 0.0,
            "answer_p95": 30.0,
            "cost_per_answer": 0.001,
        },
        "gate": {"passed": False},
    }
    path = tmp_path / "report-rescored.json"
    path.write_text(json.dumps(saved), encoding="utf-8")
    data = rescore.quality_summary([path])
    assert data["selected"] is None and data["summary"] is None
    assert data["models"][0]["model"] == "model-a"
    assert "proxy" not in json.dumps(data, ensure_ascii=False)
