"""Метрики оценки справочного поиска: ожидания, hit/recall/MRR/nDCG, перцентили, набор вопросов."""

import json
import math
from pathlib import Path

import pytest
from olymp_api.modules.assistant.references import Reference
from olymp_workers.eval_rag import (
    Outcome,
    Question,
    QuestionError,
    Spec,
    by_source_type,
    first_hit_rank,
    gains,
    hit_at,
    load_questions,
    ndcg_at,
    no_answer_report,
    parse_question,
    percentile,
    recall_at,
    reciprocal_rank,
    run_questions,
    spec_matches,
    summarize,
    unresolved,
)

REPO_DATA = Path(__file__).resolve().parents[3] / "data"


def ref(
    text: str, kind: str = "admission_rule", url: str = "https://law.example/a", rank: float = 0.9
) -> Reference:
    return Reference(kind, "Закон", url, None, text, rank)


RULE = ref("БВИ — приём без вступительных испытаний.")
YEARS = ref("Диплом действует  четыре\nгода.", url="https://law.example/b")
NOISE = ref("Погода в Москве", kind="university_document", url="https://uni.example/x")
NEED_RULE = (Spec("admission_rule", "приём без вступительных испытаний"),)
NEED_YEARS = (Spec("admission_rule", "диплом действует четыре года", url="law.example/b"),)


def test_spec_matches_ignores_case_and_whitespace() -> None:
    assert spec_matches(NEED_RULE[0], RULE)
    assert spec_matches(NEED_YEARS[0], YEARS)  # перенос строки и двойной пробел не мешают
    assert not spec_matches(NEED_YEARS[0], RULE)  # адрес не совпал
    assert not spec_matches(Spec("olympiad_card", "приём"), RULE)  # другой тип источника
    assert not spec_matches(Spec("admission_rule", "приём", title="Устав"), RULE)  # заголовок


def test_hit_rank_and_reciprocal_rank() -> None:
    needs = (NEED_RULE,)
    assert first_hit_rank(needs, [NOISE, RULE]) == 2
    assert first_hit_rank(needs, [NOISE]) is None
    assert first_hit_rank(needs, []) is None
    assert [hit_at(2, k) for k in (1, 3, 5)] == [0.0, 1.0, 1.0]
    assert hit_at(None, 5) == 0.0
    assert reciprocal_rank(4) == 0.25
    assert reciprocal_rank(None) == 0.0


def test_hit_ignores_results_beyond_k() -> None:
    assert first_hit_rank((NEED_RULE,), [NOISE] * 5 + [RULE]) is None


def test_overlapping_chunks_close_one_need_once() -> None:
    twin = ref("БВИ — приём без вступительных испытаний (продолжение).")
    assert gains((NEED_RULE, NEED_YEARS), [RULE, twin, YEARS]) == [1, 0, 1]
    assert recall_at((NEED_RULE, NEED_YEARS), [RULE, twin]) == 0.5


def test_alternatives_any_variant_closes_need() -> None:
    need = (Spec("university_document", "нет такого"), NEED_RULE[0])
    assert recall_at((need,), [NOISE, RULE]) == 1.0
    assert first_hit_rank((need,), [RULE]) == 1


def test_ndcg_prefers_early_hits() -> None:
    needs = (NEED_RULE, NEED_YEARS)
    assert ndcg_at(needs, [RULE, YEARS]) == pytest.approx(1.0)
    late = ndcg_at(needs, [NOISE, NOISE, RULE, YEARS])
    assert 0 < late < 1
    expected = (1 / math.log2(4) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
    assert late == pytest.approx(expected)
    assert ndcg_at(needs, [NOISE]) == 0.0
    assert ndcg_at((), [RULE]) == 0.0


def test_ndcg_ideal_is_capped_by_k() -> None:
    needs = tuple((Spec("admission_rule", f"слово{i}"),) for i in range(8))
    found = [ref(f"слово{i}") for i in range(5)]
    assert ndcg_at(needs, found) == pytest.approx(1.0)  # из 8 ожиданий в пять мест лучшее — пять
    assert recall_at(needs, found) == pytest.approx(5 / 8)


def test_percentile_interpolates() -> None:
    values = [10.0, 20.0, 30.0, 40.0]
    assert percentile(values, 0.5) == 25.0
    assert percentile(values, 0.0) == 10.0
    assert percentile(values, 1.0) == 40.0
    assert percentile([7.0], 0.95) == 7.0
    assert percentile([], 0.5) == 0.0
    assert percentile([5.0, 1.0, 3.0], 0.5) == 3.0  # вход не обязан быть отсортирован


def question(id: str, kind: str, *needs: tuple[Spec, ...]) -> Question:
    return Question(id, kind, f"вопрос {id}", needs)


def outcomes() -> list[Outcome]:
    return [
        Outcome(question("a", "закон", NEED_RULE), [RULE, NOISE], 0.010),
        Outcome(question("b", "закон", NEED_YEARS), [NOISE, YEARS], 0.020),
        Outcome(question("c", "вуз", NEED_RULE), [NOISE], 0.030),
        Outcome(question("none-1", "нет_ответа"), [], 0.040),
        Outcome(question("none-2", "нет_ответа"), [NOISE], 0.050),
    ]


def test_summary_groups_by_question_type_and_source() -> None:
    summary = summarize(outcomes())
    assert summary["questions"] == 5
    assert summary["with_answer"]["questions"] == 3
    assert summary["with_answer"]["hit@1"] == round(1 / 3, 3)
    assert summary["with_answer"]["hit@5"] == round(2 / 3, 3)
    assert summary["with_answer"]["mrr"] == round((1 + 0.5 + 0) / 3, 3)
    law = summary["by_question_type"]["закон"]
    assert (law["questions"], law["hit@1"], law["hit@3"]) == (2, 0.5, 1.0)
    assert summary["by_question_type"]["вуз"]["hit@5"] == 0.0
    assert "нет_ответа" not in summary["by_question_type"]
    assert summary["misses"] == ["c"]
    assert summary["latency"]["p50_ms"] == 30.0
    assert summary["latency"]["p95_ms"] == pytest.approx(48.0)


def test_by_source_type_counts_expectations() -> None:
    stats = by_source_type([o for o in outcomes() if not o.question.no_answer])
    assert stats == {"admission_rule": {"expectations": 3, "found@5": 2, "recall@5": 0.667}}


def test_no_answer_report_counts_empty_and_compares_ranks() -> None:
    all_outcomes = outcomes()
    none = [o for o in all_outcomes if o.question.no_answer]
    answered = [o for o in all_outcomes if not o.question.no_answer]
    report = no_answer_report(none, answered)
    assert report["questions"] == 2
    assert report["empty_share"] == 0.5
    assert report["top_rank_median"] == 0.9
    assert report["right_rank_median"] == 0.9
    assert no_answer_report([], [])["empty_share"] == 0.0


def test_unresolved_lists_expectations_without_fragments() -> None:
    questions = [
        question("a", "закон", NEED_RULE),
        question("b", "закон", NEED_RULE, (Spec("olympiad_card", "нет такого"),)),
    ]
    assert unresolved(questions, [RULE, NOISE]) == ["b#2"]


async def test_run_questions_takes_best_time_and_last_result() -> None:
    calls: list[str] = []

    async def search(text: str) -> list[Reference]:
        calls.append(text)
        return [RULE]

    result = await run_questions([question("a", "закон", NEED_RULE)], search, repeats=3)
    assert calls == ["вопрос a"] * 3
    assert result[0].rank == 1
    assert result[0].seconds >= 0


def raw(**fields: object) -> dict[str, object]:
    base = {"id": "x", "type": "закон", "question": "Что такое БВИ?"}
    return {**base, **fields}


def test_parse_question_reads_variants_and_no_answer() -> None:
    spec = {"source_type": "admission_rule", "phrase": "бви"}
    parsed = parse_question(raw(expect=[spec, [spec, {**spec, "url": "x"}]]), 1)
    assert [len(need) for need in parsed.needs] == [1, 2]
    assert parse_question(raw(no_answer=True), 1).no_answer
    with pytest.raises(QuestionError):
        parse_question(raw(), 1)  # ни ожиданий, ни no_answer
    with pytest.raises(QuestionError):
        parse_question(raw(expect=[spec], no_answer=True), 1)
    with pytest.raises(QuestionError):
        parse_question(raw(expect=[{"source_type": "admission_rule"}]), 1)  # без фразы
    with pytest.raises(QuestionError):
        parse_question({"id": "x", "type": "t"}, 1)


def test_load_questions_rejects_duplicate_ids(tmp_path: Path) -> None:
    spec = {"source_type": "admission_rule", "phrase": "бви"}
    line = json.dumps(raw(expect=[spec]), ensure_ascii=False)
    path = tmp_path / "q.jsonl"
    path.write_text(line + "\n\n" + line + "\n", encoding="utf-8")
    with pytest.raises(QuestionError):
        load_questions(path)


def test_committed_question_set_is_well_formed() -> None:
    questions = load_questions(REPO_DATA / "eval" / "rag" / "questions.jsonl")
    assert 50 <= len(questions) <= 60
    empty = [q for q in questions if q.no_answer]
    assert 5 <= len(empty) <= 8
    assert {q.id for q in empty} == {q.id for q in questions if q.type == "нет_ответа"}
    assert {s.source_type for q in questions for need in q.needs for s in need} == {
        "admission_rule",
        "olympiad_card",
        "olympiad_material",
        "university_document",
    }
