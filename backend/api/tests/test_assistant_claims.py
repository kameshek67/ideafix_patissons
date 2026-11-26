"""Проверки утверждений по базе (claims) и ожидания набора (expectations) без базы."""

from typing import Any

import pytest
from olymp_api.llm import TextDelta
from olymp_api.llm.fake import FakeProvider
from olymp_api.modules.assistant import evaluate
from olymp_api.modules.assistant.claims import Ledger, Row, check_claims, extract, role_kind
from olymp_api.modules.assistant.expectations import Spec, assess
from olymp_api.modules.assistant.factcheck import Entity, Vocabulary

HSE, ITMO, MIPT, HSE_SPB = 1, 2, 3, 4
VP, NTO, FIZTEH, VSOSH, SPBGU_OLY = 10, 11, 12, 13, 14


@pytest.fixture(scope="module")
def vocab() -> Vocabulary:
    v = Vocabulary()
    v.add_university(HSE, "НИУ ВШЭ (Москва)", "НИУ ВШЭ (Москва)")
    v.add_university(HSE_SPB, "НИУ ВШЭ — Санкт-Петербург", "НИУ ВШЭ — Санкт-Петербург")
    v.add_university(ITMO, "Университет ИТМО", "Университет ИТМО")
    v.add_university(MIPT, "МФТИ", "МФТИ")
    v.add_university(20, "СПбГУ", "СПбГУ")
    for id_, label, *aliases in [
        (VP, "«Высшая проба»", "высшая проба"),
        (NTO, "НТО"),
        (FIZTEH, "«Физтех»", "физтех"),
        (VSOSH, "ВсОШ", "всош"),
        (SPBGU_OLY, "Олимпиада СПбГУ"),
        (21, "СПбГУ"),
    ]:
        v.add(Entity("olympiad", id_, label), label, *aliases)
    return v


def row(
    uni: int,
    oly: int | None,
    kind: str,
    role: str = "",
    subject: str = "",
    score: int | None = None,
) -> Row:
    return Row.build(uni, oly, kind, role, subject, score)


@pytest.fixture
def ledger() -> Ledger:
    """Что «в базе»: ВШЭ × Высшая проба — БВИ только победителям (математика, 85), ВШЭ × НТО —
    100 баллов победителям и призёрам (информатика, 75), ИТМО × Высшая проба — БВИ обоим."""
    return Ledger.of(
        [
            row(HSE, VP, "БВИ", "только победители", "математика", 85),
            row(HSE, NTO, "100 баллов", "победители и призёры", "информатика", 75),
            row(ITMO, VP, "БВИ", "победители и призёры"),
            row(ITMO, NTO, "БВИ", "победители"),
            row(ITMO, NTO, "БВИ", "победители и призёры"),
            row(HSE, FIZTEH, "Особое право (БВИ/100)", "победители и призёры"),
            row(MIPT, None, "БВИ", "только победители"),
        ]
    )


def kinds(answer: str, vocab: Vocabulary, ledger: Ledger) -> list[tuple[str, str]]:
    return [(v.kind, v.fragment) for v in check_claims(answer, vocab, ledger)]


def test_roles_from_base_rows() -> None:
    assert role_kind("только победители") == "winners"
    assert role_kind("победители и призёры (10–11 класс)") == "both"
    assert role_kind("призёры") == "prizers"
    assert role_kind("") == "unknown"
    assert role_kind("члены сборных команд РФ") == "unknown"


# (а) кому: победителям и призёрам / только победителям


def test_prizers_claimed_when_base_has_only_winners(vocab: Vocabulary, ledger: Ledger) -> None:
    answer = "В ВШЭ (Москва) «Высшая проба» даёт БВИ победителям и призёрам."
    assert kinds(answer, vocab, ledger) == [("role", "призёрам")]
    assert kinds("Призёрам «Высшей пробы» в НИУ ВШЭ (Москва) дают БВИ.", vocab, ledger) == [
        ("role", "Призёрам")
    ]


def test_only_winners_claimed_when_base_has_prizers_too(vocab: Vocabulary, ledger: Ledger) -> None:
    answer = "НТО в НИУ ВШЭ (Москва) даёт 100 баллов только победителям."
    assert kinds(answer, vocab, ledger) == [("role", "только победителям")]


def test_correct_roles_are_not_flagged(vocab: Vocabulary, ledger: Ledger) -> None:
    for answer in [
        "«Высшая проба» в НИУ ВШЭ (Москва) даёт БВИ только победителям.",
        "НТО в НИУ ВШЭ (Москва) даёт 100 баллов победителям и призёрам.",
        # у ИТМО × НТО есть и строка для победителей, и для обоих: любая подтверждает
        "НТО в Университете ИТМО даёт БВИ победителям и призёрам.",
        "НТО в Университете ИТМО даёт БВИ только победителям.",
    ]:
        assert kinds(answer, vocab, ledger) == [], answer


def test_negated_and_split_role_clauses_are_skipped(vocab: Vocabulary, ledger: Ledger) -> None:
    for answer in [
        "Призёрам «Высшей пробы» в НИУ ВШЭ (Москва) БВИ не дают.",
        "В НИУ ВШЭ (Москва) «Высшая проба» даёт БВИ победителям, а призёрам — нет.",
    ]:
        assert kinds(answer, vocab, ledger) == [], answer


def test_role_is_bound_to_its_benefit_type(vocab: Vocabulary) -> None:
    """«БВИ только победителям, призёрам — 100 баллов»: у призёров проверяется 100 баллов."""
    base = Ledger.of(
        [
            row(HSE, VP, "БВИ", "только победители"),
            row(HSE, VP, "100 баллов", "победители и призёры"),
        ]
    )
    answer = "В НИУ ВШЭ (Москва) «Высшая проба» даёт БВИ только победителям, призёрам — 100 баллов."
    assert kinds(answer, vocab, base) == []
    swapped = "В НИУ ВШЭ (Москва) «Высшая проба» даёт БВИ призёрам, победителям — 100 баллов."
    assert kinds(swapped, vocab, base) == [("role", "призёрам")]


def test_unknown_role_in_base_is_not_contradicted(vocab: Vocabulary) -> None:
    base = Ledger.of([row(HSE, VP, "БВИ", "")])
    assert kinds("НИУ ВШЭ (Москва) даёт БВИ за «Высшую пробу» призёрам.", vocab, base) == []


# (б) БВИ или 100 баллов


def test_benefit_type_swapped(vocab: Vocabulary, ledger: Ledger) -> None:
    bvi_instead = "НТО в НИУ ВШЭ (Москва) даёт БВИ."
    assert kinds(bvi_instead, vocab, ledger) == [("benefit_type", "БВИ")]
    hundred_instead = "«Высшая проба» в НИУ ВШЭ (Москва) даёт 100 баллов."
    assert kinds(hundred_instead, vocab, ledger) == [("benefit_type", "100 баллов")]


def test_benefit_type_correct_or_special_is_not_flagged(vocab: Vocabulary, ledger: Ledger) -> None:
    for answer in [
        "НТО в НИУ ВШЭ (Москва) даёт 100 баллов за ЕГЭ.",
        "«Физтех» в НИУ ВШЭ (Москва) даёт БВИ.",  # «особое право» — и БВИ, и 100 баллов
        "«Физтех» в НИУ ВШЭ (Москва) даёт 100 баллов.",
        "Призёру — 100 баллов, а не БВИ: НТО в НИУ ВШЭ (Москва).",
    ]:
        assert kinds(answer, vocab, ledger) == [], answer


# (в) порог ЕГЭ


def test_threshold_wrong_number(vocab: Vocabulary, ledger: Ledger) -> None:
    answer = "«Высшая проба» в НИУ ВШЭ (Москва): БВИ победителям, нужен ЕГЭ по математике от 90."
    found = check_claims(answer, vocab, ledger)
    assert [(v.kind, v.fragment) for v in found] == [("threshold", "от 90")]
    assert "85" in found[0].detail


def test_threshold_wrong_subject(vocab: Vocabulary, ledger: Ledger) -> None:
    answer = "«Высшая проба» в НИУ ВШЭ (Москва): БВИ победителям, нужен ЕГЭ по физике от 85."
    found = check_claims(answer, vocab, ledger)
    assert [(v.kind, v.fragment) for v in found] == [("threshold", "от 85")]
    assert "математика" in found[0].detail


def test_threshold_subject_swapped_between_pairs(vocab: Vocabulary, ledger: Ledger) -> None:
    """85 есть в базе, но для математики у Высшей пробы, а не для информатики у НТО."""
    answer = "НТО в НИУ ВШЭ (Москва) даёт 100 баллов, подтверждение — ЕГЭ по информатике от 85."
    assert kinds(answer, vocab, ledger) == [("threshold", "от 85")]


def test_threshold_correct_is_not_flagged(vocab: Vocabulary, ledger: Ledger) -> None:
    for answer in [
        "«Высшая проба» в НИУ ВШЭ (Москва): БВИ победителям, ЕГЭ по математике от 85.",
        "НТО в НИУ ВШЭ (Москва): 100 баллов, ЕГЭ по информатике от 75.",
        "«Высшая проба» в Университете ИТМО: БВИ, ЕГЭ по математике от 99.",  # порога в базе нет
    ]:
        assert kinds(answer, vocab, ledger) == [], answer


def test_threshold_in_row_without_subject_fits_any_subject(vocab: Vocabulary) -> None:
    base = Ledger.of([row(HSE, VP, "БВИ", "победители", "", 75)])
    answer = "«Высшая проба» в НИУ ВШЭ (Москва): ЕГЭ по физике от 75."
    assert kinds(answer, vocab, base) == []


# (г) олимпиады нет в перечне вуза


def test_olympiad_not_in_university_list(vocab: Vocabulary, ledger: Ledger) -> None:
    answer = "В МФТИ «Высшая проба» даёт БВИ."
    found = check_claims(answer, vocab, ledger)
    assert [(v.kind, v.fragment) for v in found] == [("not_listed", "МФТИ")]
    assert "Высшая проба" in found[0].detail
    assert kinds("НТО даёт БВИ в Университете ИТМО.", vocab, ledger) == []


def test_not_listed_skips_negations_and_ambiguous_sentences(
    vocab: Vocabulary, ledger: Ledger
) -> None:
    for answer in [
        "В МФТИ «Высшая проба» БВИ не даёт.",
        "Про «Высшую пробу» в МФТИ в базе нет данных.",
        # несколько вузов и несколько олимпиад: непонятно, какая пара имеется в виду
        "«Высшая проба» и НТО дают БВИ в МФТИ и Университете ИТМО.",
        # названо только одно: пара не составляется
        "МФТИ даёт БВИ.",
    ]:
        assert kinds(answer, vocab, ledger) == [], answer


def test_not_listed_for_each_university_of_a_list(vocab: Vocabulary, ledger: Ledger) -> None:
    answer = "НТО даёт БВИ в Университете ИТМО, МФТИ и НИУ ВШЭ (Москва)."
    assert kinds(answer, vocab, ledger) == [("not_listed", "МФТИ")]


def test_list_item_takes_olympiad_from_the_intro(vocab: Vocabulary, ledger: Ledger) -> None:
    answer = (
        "«Высшая проба» даёт БВИ в таких вузах:\n\n"
        "- Университет ИТМО: победителям и призёрам.\n"
        "- МФТИ: победителям и призёрам.\n"
        "- НИУ ВШЭ (Москва): победителям и призёрам."
    )
    found = {(v.kind, v.fragment) for v in check_claims(answer, vocab, ledger)}
    assert found == {("not_listed", "МФТИ"), ("role", "призёрам")}


def test_ambiguous_names_are_not_checked(vocab: Vocabulary, ledger: Ledger) -> None:
    """СПбГУ — и вуз, и олимпиада: что имеется в виду, без контекста не понять."""
    assert kinds("СПбГУ даёт БВИ за НТО.", vocab, ledger) == []


def test_unloaded_university_is_not_judged(vocab: Vocabulary) -> None:
    """Пока строки вуза не загружены, «в перечне нет» сказать нельзя."""
    empty = Ledger()
    assert kinds("В МФТИ «Высшая проба» даёт БВИ победителям и призёрам.", vocab, empty) == []


def test_claims_are_extracted_by_clause(vocab: Vocabulary) -> None:
    answer = "В НИУ ВШЭ (Москва) НТО даёт БВИ, а ЕГЭ по математике от 75 нужен призёрам."
    claims = extract(answer, vocab.find(answer))
    assert [c.clause for c in claims][0].startswith("В НИУ ВШЭ")
    assert any(c.prizers and c.thresholds == [("математика", 75, "от 75")] for c in claims)


# ---------------------------------------------------------------- ожидания набора


def test_assess_facts_and_forbidden(vocab: Vocabulary) -> None:
    spec = Spec.parse(
        {
            "data": "present",
            "facts": [
                {
                    "universities": ["НИУ ВШЭ (Москва)"],
                    "olympiads": ["«Высшая проба»"],
                    "benefit": "БВИ",
                    "who": "winners",
                }
            ],
            "forbidden": [
                {
                    "universities": ["НИУ ВШЭ (Москва)"],
                    "olympiads": ["«Высшая проба»"],
                    "benefit": "БВИ",
                    "who": "prizers",
                },
                {"universities": ["МФТИ"], "olympiads": ["«Высшая проба»"]},
            ],
        }
    )
    good = assess(spec, "В НИУ ВШЭ (Москва) «Высшая проба» даёт БВИ только победителям.", vocab)
    assert good.found == [True] and good.hits == [] and not good.no_data
    # правильный вуз и олимпиада, но «кому» перепутано: факта нет, запрет сработал
    bad = assess(spec, "В НИУ ВШЭ (Москва) «Высшая проба» даёт БВИ победителям и призёрам.", vocab)
    assert bad.found == [False] and bad.hits_who == 1 and bad.missing
    elsewhere = assess(spec, "«Высшая проба» даёт льготы в МФТИ.", vocab)
    assert elsewhere.hits and elsewhere.found == [False]


def test_assess_min_count_and_absent(vocab: Vocabulary) -> None:
    spec = Spec.parse(
        {
            "data": "present",
            "facts": [
                {
                    "universities": ["Университет ИТМО", "МФТИ", "НИУ ВШЭ (Москва)"],
                    "olympiads": ["НТО"],
                    "min": 2,
                }
            ],
        }
    )
    assert assess(spec, "НТО даёт БВИ в Университете ИТМО.", vocab).found == [False]
    assert assess(spec, "НТО даёт БВИ в Университете ИТМО и НИУ ВШЭ (Москва).", vocab).found == [
        True
    ]
    no_data = assess(Spec(data="absent"), "По этой олимпиаде в базе нет данных.", vocab)
    assert no_data.no_data
    assert not assess(Spec(data="absent"), "Эта олимпиада даёт БВИ.", vocab).no_data


def test_forbidden_university_family_needs_all_campuses(vocab: Vocabulary) -> None:
    """«ВШЭ» — несколько кампусов: запрет на один кампус не срабатывает на общее «ВШЭ»."""
    spec = Spec.parse(
        {"forbidden": [{"universities": ["НИУ ВШЭ — Санкт-Петербург"], "benefit": "БВИ"}]}
    )
    assert assess(spec, "В ВШЭ дают БВИ.", vocab).hits == []
    assert assess(spec, "В НИУ ВШЭ — Санкт-Петербург дают БВИ.", vocab).hits


# ---------------------------------------------------------------- до и после фактчекера


async def test_raw_and_final_errors_are_counted_apart(vocab: Vocabulary, ledger: Ledger) -> None:
    wrong = "В НИУ ВШЭ (Москва) «Высшая проба» даёт БВИ победителям и призёрам."
    right = "В НИУ ВШЭ (Москва) «Высшая проба» даёт БВИ только победителям."
    fake = FakeProvider([[TextDelta(wrong)], [TextDelta(right)]])
    case = evaluate.parse_case(
        {
            "id": "x",
            "question": "Я призёр Высшей пробы, ВШЭ даст БВИ?",
            "expect": {
                "data": "present",
                "facts": [
                    {
                        "universities": ["НИУ ВШЭ (Москва)"],
                        "olympiads": ["«Высшая проба»"],
                        "benefit": "БВИ",
                        "who": "winners",
                    }
                ],
                "forbidden": [
                    {
                        "universities": ["НИУ ВШЭ (Москва)"],
                        "olympiads": ["«Высшая проба»"],
                        "benefit": "БВИ",
                        "who": "prizers",
                    }
                ],
            },
        }
    )
    outcome = await evaluate.run_case(case, fake, None, vocab, ledger)
    turn = outcome.turns[0]
    # ученик получил исправленный ответ, а сырой ответ модели остался в отчёте с ошибкой «кому»
    assert turn.answer == right and turn.raw_answer == wrong and turn.retried
    assert [v.kind for v in turn.raw_violations] == ["role"]
    assert turn.violations == []
    assert turn.raw_expected is not None and turn.raw_expected.hits_who == 1
    assert turn.expected is not None and turn.expected.found == [True]
    assert outcome.passed, outcome.reasons
    # повтор просит исправить именно по базе, с причиной
    note = fake.requests[-1]["messages"][-1]["content"]
    assert "по базе это неверно" in note and "призёрам" in note

    data = evaluate.report([outcome], "fake")["summary"]
    assert (data["error_share_raw"], data["error_share_final"]) == (1.0, 0.0)
    assert (data["who_type_errors_raw"], data["who_type_errors_final"]) == (1, 0)
    assert (
        data["error_kinds_raw"] == {"forbidden": 1, "role": 1} and data["error_kinds_final"] == {}
    )


async def test_cut_answer_with_base_error_goes_to_no_data(
    vocab: Vocabulary, ledger: Ledger
) -> None:
    wrong = "В МФТИ «Высшая проба» даёт БВИ."
    fake = FakeProvider([[TextDelta(wrong)], [TextDelta(wrong)]])
    case = evaluate.parse_case({"id": "x", "question": "Что в МФТИ?", "expect": {"data": "absent"}})
    outcome = await evaluate.run_case(case, fake, None, vocab, ledger)
    turn = outcome.turns[0]
    assert turn.answer.startswith("По этому вопросу в базе нет данных")
    # МФТИ нет в данных диалога (entity) и нет в перечне олимпиады (not_listed)
    assert {v.kind for v in turn.raw_violations} == {"entity", "not_listed"}
    assert turn.violations == [] and outcome.passed
    data = evaluate.report([outcome], "fake")["summary"]
    assert (data["fabrication_raw"], data["fabrication_final"]) == (1.0, 0.0)


async def test_no_data_where_data_exists_is_counted(vocab: Vocabulary) -> None:
    fake = FakeProvider([[TextDelta("В базе нет данных по этой олимпиаде.")]])
    case = evaluate.parse_case(
        {
            "id": "x",
            "question": "Что даёт НТО в ИТМО?",
            "expect": {
                "data": "present",
                "facts": [{"universities": ["Университет ИТМО"], "olympiads": ["НТО"]}],
            },
        }
    )
    outcome = await evaluate.run_case(case, fake, None, vocab)
    data = evaluate.report([outcome], "fake")["summary"]
    assert (data["no_data_where_data_raw"], data["no_data_where_data_final"]) == (1.0, 1.0)
    assert data["facts_found_share"] == 0.0 and not outcome.passed


async def test_usage_and_cost_are_summed(vocab: Vocabulary) -> None:
    from olymp_api.llm import Usage

    fake = FakeProvider([[TextDelta("Привет! Чем увлекаешься?"), Usage(1000, 200, 0.5)]])
    outcome = await evaluate.run_case(
        evaluate.Case.single("a", "Привет", clarify=True), fake, None, vocab
    )
    turn = outcome.turns[0]
    assert (turn.prompt_tokens, turn.completion_tokens, turn.cost) == (1000, 200, 0.5)
    data = evaluate.report([outcome], "fake")["summary"]
    assert (data["tokens_prompt"], data["cost_total"], data["cost_source"]) == (
        1000,
        0.5,
        "провайдер",
    )
    # провайдер цену не отдал — считаем по цене за миллион токенов
    plain = FakeProvider([[TextDelta("Чем увлекаешься?"), Usage(1_000_000, 500_000)]])
    out = await evaluate.run_case(evaluate.Case.single("b", "Привет"), plain, None, vocab)
    priced: Any = evaluate.summary([out], price_in=2.0, price_out=4.0)
    assert (priced["cost_total"], priced["cost_per_answer"]) == (4.0, 4.0)


def test_gate() -> None:
    ok = {"error_share_final": 0.04, "who_type_errors_final": 0, "answer_p95": 12.0}
    assert evaluate.gate(ok)["passed"]
    assert not evaluate.gate({**ok, "who_type_errors_final": 1})["passed"]
    assert not evaluate.gate({**ok, "error_share_final": 0.06})["passed"]
    assert not evaluate.gate({**ok, "answer_p95": 25.0})["passed"]
