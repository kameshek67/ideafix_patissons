"""Проверка ответа по фактам диалога (factcheck) и многоходовая оценка (evaluate) без базы."""

import json
from typing import Any

import pytest
from olymp_api.llm import TextDelta, ToolCall, ToolCalls
from olymp_api.llm.fake import FakeProvider
from olymp_api.modules.assistant import evaluate
from olymp_api.modules.assistant.factcheck import Entity, Facts, Vocabulary, check, sentences
from olymp_api.modules.assistant.service import CUT_NOTE, DISCLAIMER
from olymp_api.modules.assistant.tools import HANDLERS, ToolContext, ToolResult


def olympiad(id_: int, label: str, *aliases: str) -> tuple[Entity, tuple[str, ...]]:
    return Entity("olympiad", id_, label), (label, *aliases)


@pytest.fixture(scope="module")
def vocab() -> Vocabulary:
    """Названия как в базе: краткие и полные имена вузов, олимпиады с алиасами из справочника."""
    v = Vocabulary()
    for id_, name, short in [
        (1, "МГУ им. М.В. Ломоносова", "МГУ им. М.В. Ломоносова"),
        (2, "НИУ ВШЭ (Москва)", "НИУ ВШЭ (Москва)"),
        (3, "НИУ ВШЭ — Пермь", "НИУ ВШЭ — Пермь"),
        (4, "Университет ИТМО", "Университет ИТМО"),
        (5, "МФТИ", "МФТИ"),
        (6, "СПбГУ", "СПбГУ"),
        (7, "НИЯУ МИФИ", "НИЯУ МИФИ"),
        (8, "Казанский (Приволжский) федеральный университет (КФУ)", "КФУ"),
        (9, "Не указан", "Не указан"),
    ]:
        v.add_university(id_, name, short)
    for entity, names in [
        olympiad(1, "НТО", "Национальная технологическая олимпиада", "нто", "нти"),
        olympiad(2, "«Юниор»", "юниор", "Конкурс «Юниор»"),
        olympiad(3, "«Высшая проба»", "вышка", "Олимпиада школьников «Высшая проба»"),
        olympiad(4, "«Физтех»", "физтех", "мфти", "Олимпиада школьников «Физтех»"),
        olympiad(5, "ВсОШ", "всош", "вош", "всероссийская олимпиада", "заключительный этап"),
        olympiad(6, "Олимпиада СПбГУ", "спбгу"),
        olympiad(7, "«Звезда»", "звезда"),
        olympiad(8, "Логично?!", "логично"),
        olympiad(9, "Информатика и программирование"),
        olympiad(10, "Юный историк"),
        olympiad(11, "«Ломоносов»", "ломоносов"),
        olympiad(12, "Олимпиада по ИИ"),
        olympiad(13, "«Покори Воробьёвы горы!»", "пвг"),
    ]:
        v.add(entity, *names)
    return v


PMI = json.dumps(
    {
        "university": "НИУ ВШЭ (Москва)",
        "program": "№3. Прикладная математика и информатика (01.03.02)",
        "code": "01.03.02",
        "olympiads": [
            {
                "olympiad_id": 5,
                "olympiad": "«Высшая проба»",
                "types": ["БВИ", "100 баллов"],
                "conditions": [
                    {"who": "только победители", "grade": "11 класс", "min_ege": "85 и более"},
                    {"who": "только победители", "grade": "11 класс", "min_ege": "90 и более"},
                ],
            },
            {"olympiad_id": 9, "olympiad": "МОШ", "types": ["БВИ"]},
        ],
        "other_programs_found": 0,
    },
    ensure_ascii=False,
)
PROFILES = json.dumps(
    {
        "profiles": [
            {
                "olympiad_id": 14,
                "olympiad": "НТО",
                "profile_id": 100,
                "profile": "разработка мобильных приложений",
                "level": "III",
                "benefits": ["БВИ", "100 баллов"],
                "universities": 10,
            },
            {
                "olympiad_id": 21,
                "olympiad": "«Юниор»",
                "profile_id": 114,
                "profile": "инженерные науки",
                "track": "Разработка мобильных приложений под Android",
                "level": "I",
                "benefits": ["БВИ", "100 баллов"],
                "universities": 12,
            },
        ]
    },
    ensure_ascii=False,
)
JUNIOR_CARD = json.dumps(
    {"olympiad": "«Юниор»", "grades": "9–11", "summary": "Конкурс НИЯУ МИФИ: проектная работа"},
    ensure_ascii=False,
)


def kinds(answer: str, facts: Facts, vocab: Vocabulary) -> list[tuple[str, str]]:
    return [(v.kind, v.fragment) for v in check(answer, facts, vocab)]


# ---------------------------------------------------------------- корректные ответы


def test_correct_answer_from_tool_json_is_clean(vocab: Vocabulary) -> None:
    facts = Facts.collect([PMI, PROFILES], ["Хочу в ВШЭ на ПМИ"])
    answer = (
        "Для ПМИ в НИУ ВШЭ подойдут:\n\n"
        "1. «Высшая проба» — БВИ только победителям 11 класса: ЕГЭ по математике от 85 баллов, "
        "по информатике — не ниже 90.\n"
        "2. МОШ — тоже БВИ.\n"
        "3. НТО, профиль «Разработка мобильных приложений» (III уровень): БВИ и 100 баллов "
        "в 10 вузах.\n"
        "4. «Юниор» — секция «Разработка мобильных приложений под Android», I уровень, "
        "12 вузов.\n\n"
        "Проверь условия в правилах приёма вуза: они меняются каждый год."
    )
    assert check(answer, facts, vocab) == []


def test_inflected_names_and_aliases_are_known(vocab: Vocabulary) -> None:
    facts = Facts.collect([PMI])
    assert check("За Высшую пробу дают БВИ. Вышка — это она же.", facts, vocab) == []


def test_hundred_points_and_list_numbers_are_not_facts(vocab: Vocabulary) -> None:
    facts = Facts.collect([PROFILES])
    answer = "1. НТО даёт 100 баллов за ЕГЭ.\n2) «Юниор» тоже даёт 100 баллов.\n3. Выбирай."
    assert check(answer, facts, vocab) == []


def test_names_and_numbers_from_student_are_allowed(vocab: Vocabulary) -> None:
    facts = Facts.collect([], ["Хочу в МФТИ или СПбГУ, я в 9 классе, ЕГЭ сдам на 80"])
    answer = "Понял: ты в 9 классе и целишься в МФТИ или СПбГУ с ЕГЭ от 80 баллов."
    assert check(answer, facts, vocab) == []


def test_common_words_and_generic_names_do_not_trigger(vocab: Vocabulary) -> None:
    facts = Facts()
    answer = (
        "Это логично: на грани возможностей — звезда класса. Олимпиада по информатике и "
        "программированию тебе подойдёт, как и олимпиада по ИИ. Юный историк найдёт своё. "
        "Заключительный этап — самый сложный, не указан срок. Всероссийская олимпиада — тоже "
        "вариант; нто и вош строчными — не названия."
    )
    assert [k for k in kinds(answer, facts, vocab) if k[0] == "entity"] == []


def test_namesake_in_university_name_is_not_olympiad(vocab: Vocabulary) -> None:
    facts = Facts.collect(['{"university": "МГУ им. М.В. Ломоносова"}'])
    assert check("БВИ дают в МГУ им. М.В. Ломоносова.", facts, vocab) == []


def test_grade_range_from_card_allows_inner_grade(vocab: Vocabulary) -> None:
    facts = Facts.collect([JUNIOR_CARD])
    assert check("«Юниор» — для 9–11 классов, можно и в 10 классе.", facts, vocab) == []


# ---------------------------------------------------------------- выдумки


def test_invented_university_is_caught(vocab: Vocabulary) -> None:
    facts = Facts.collect([PMI])
    found = check("За «Высшую пробу» БВИ дают НИУ ВШЭ и МГУ.", facts, vocab)
    assert [(v.kind, v.fragment, v.detail) for v in found] == [
        ("entity", "МГУ", "вуз не из данных")
    ]
    assert found[0].sentence == "За «Высшую пробу» БВИ дают НИУ ВШЭ и МГУ."


def test_invented_olympiad_and_campus_are_caught(vocab: Vocabulary) -> None:
    facts = Facts.collect([PMI])
    assert kinds(
        "Ещё подойдут ВсОШ и «Ломоносов», а льготы есть в НИУ ВШЭ — Пермь.", facts, vocab
    ) == [
        ("entity", "ВсОШ"),
        ("entity", "Ломоносов"),
        ("entity", "НИУ ВШЭ — Пермь"),
    ]


def test_university_after_preposition_is_not_olympiad(vocab: Vocabulary) -> None:
    """«МФТИ» — и вуз, и алиас олимпиады «Физтех»: «льготы в МФТИ» — про вуз."""
    facts = Facts.collect(['{"olympiad": "«Физтех»"}'])
    assert kinds("За «Физтех» льготы есть в МФТИ.", facts, vocab) == [("entity", "МФТИ")]


def test_name_from_unread_card_is_caught(vocab: Vocabulary) -> None:
    facts = Facts.collect([PROFILES])
    assert kinds("«Юниор» проводит НИЯУ МИФИ.", facts, vocab) == [("entity", "НИЯУ МИФИ")]


@pytest.mark.parametrize(
    "answer",
    [
        "Нужен ЕГЭ от 80.",
        "Порог — 80 баллов по математике.",
        "ЕГЭ по информатике ≥ 75.",
        "Нужно не ниже 75 по профильной математике.",
    ],
)
def test_invented_ege_threshold_is_caught(vocab: Vocabulary, answer: str) -> None:
    facts = Facts.collect([PMI])
    assert [k for k, _ in kinds(answer, facts, vocab)] == ["number"]


def test_true_ege_threshold_passes(vocab: Vocabulary) -> None:
    facts = Facts.collect([PMI])
    assert check("ЕГЭ по математике от 85, по информатике ≥ 90 баллов.", facts, vocab) == []


def test_grade_needs_grade_fact(vocab: Vocabulary) -> None:
    """9 есть в фактах как число направлений и в коде 09.03.02 — классом это не делает."""
    facts = Facts.collect(['{"programs": 9, "examples": ["09.03.02 Информатика"]}'])
    assert kinds("Это для 9–11 классов.", facts, vocab) == [("number", "9–11 классов")]


def test_counts_and_levels_are_checked(vocab: Vocabulary) -> None:
    facts = Facts.collect([PROFILES, '{"olympiad_id": 15}'])
    assert kinds("НТО даёт БВИ в 15 вузах, это II уровень.", facts, vocab) == [
        ("number", "15 вузах"),
        ("number", "II уровень"),
    ]


def test_hedge_about_olympiad_is_caught(vocab: Vocabulary) -> None:
    facts = Facts.collect(['{"olympiad": "«Физтех»", "note": "Карточки нет"}'])
    found = check(
        "Карточки «Физтеха» в базе нет. Профилей 10 — обычно это математика и физика. "
        "Как правило, отбор онлайн.",
        facts,
        vocab,
    )
    assert [(v.kind, v.fragment) for v in found] == [
        ("hedge", "обычно"),
        ("hedge", "Как правило"),
    ]


def test_hedge_without_facts_is_allowed(vocab: Vocabulary) -> None:
    assert check("Обычно я отвечаю быстро — спрашивай!", Facts(), vocab) == []


def test_younger_grades_claim_is_not_caught_by_words(vocab: Vocabulary) -> None:
    """Выдумка из раздела 1 плана: «Юниор» для младших классов. Чисел в ней нет, поэтому
    factcheck её не видит — её ловит exclude «младш» в наборе оценки."""
    facts = Facts.collect([PROFILES])
    answer = "«Юниор» рассчитан как раз на младшие классы."
    assert check(answer, facts, vocab) == []
    assert evaluate.judge(evaluate.Check(exclude=["младш"]), answer, [], None)


def test_sentences_keep_initials_together() -> None:
    text = "БВИ в МГУ им. М.В. Ломоносова. Обычно так.\n- пункт"
    assert [text[a:b] for a, b in sentences(text)] == [
        "БВИ в МГУ им. М.В. Ломоносова.",
        "Обычно так.",
        "- пункт",
    ]


# ---------------------------------------------------------------- многоходовая оценка без базы


def call(name: str, arguments: dict[str, Any], id_: str) -> ToolCalls:
    return ToolCalls((ToolCall(id_, name, json.dumps(arguments, ensure_ascii=False)),))


@pytest.fixture
def fake_tools(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Инструменты без базы: run_tool берёт обработчик из HANDLERS в момент вызова."""
    calls: list[str] = []

    async def program(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        calls.append("olympiads_for_program")
        return ToolResult(PMI)

    monkeypatch.setitem(HANDLERS, "olympiads_for_program", program)
    return calls


async def test_dialog_runs_turn_by_turn(vocab: Vocabulary, fake_tools: list[str]) -> None:
    fake = FakeProvider(
        [
            [TextDelta("Ищу…"), call("olympiads_for_program", {"university": "ВШЭ"}, "c1")],
            [TextDelta("Подойдут «Высшая проба» и МОШ: победителям 11 класса — ЕГЭ от 85.")],
            [TextDelta("Только победителям 11 класса, ЕГЭ от 85; обычно регистрация осенью.")],
            # проверка ответа (V4) поймала «обычно» и попросила переписать
            [TextDelta("Только победителям 11 класса, ЕГЭ от 85.")],
        ]
    )
    case = evaluate.parse_case(
        {
            "id": "pmi",
            "turns": ["Хочу в ВШЭ на ПМИ", "А какой балл ЕГЭ?"],
            "checks": [
                {"tools": ["olympiads_for_program"], "include": ["Высшая проба"]},
                {"must_mention_conditions": ["85", "победител"], "max_tools": 0},
            ],
        }
    )
    outcome = await evaluate.run_case(case, fake, None, vocab)

    first, second = outcome.turns
    assert fake_tools == ["olympiads_for_program"]
    assert (first.tools, first.rounds, first.tool_results) == (["olympiads_for_program"], 2, [PMI])
    # текст до поиска («Ищу…») не входит в ответ, оговорка — отдельно
    assert first.answer == "Подойдут «Высшая проба» и МОШ: победителям 11 класса — ЕГЭ от 85."
    assert (first.notice, second.notice) == (DISCLAIMER, None)
    assert (second.tools, second.rounds) == ([], 2)
    assert first.first_delta is not None and second.first_delta is not None
    assert first.first_visible is not None and first.first_visible <= first.first_delta
    # история как на сайте: прошлый ответ целиком — сообщение помощника
    history = fake.requests[2]["messages"]
    assert [m["role"] for m in history] == ["system", "user", "assistant", "user"]
    assert history[2]["content"] == first.answer
    # «обычно» — догадка: до ученика дошёл переписанный ответ без неё; «85» и «11 класс» —
    # из прошлого проверенного ответа (его отпечаток в контексте диалога), это не выдумка
    retry = fake.requests[-1]
    assert retry["tools"] == [] and "«обычно»" in retry["messages"][-1]["content"]
    assert second.answer == "Только победителям 11 класса, ЕГЭ от 85."
    assert outcome.conditions_named is True
    assert outcome.violations == []
    assert outcome.passed


async def test_dialog_catches_invented_fact_in_follow_up(
    vocab: Vocabulary, fake_tools: list[str]
) -> None:
    fake = FakeProvider(
        [
            [call("olympiads_for_program", {"university": "ВШЭ"}, "c1")],
            [TextDelta("Подойдут «Высшая проба» и МОШ.")],
            [call("olympiads_for_program", {"university": "ВШЭ"}, "c2")],
            [TextDelta("Нужен ЕГЭ от 85. Ещё БВИ дают в МГУ.")],
            [TextDelta("Нужен ЕГЭ от 85. Обычно БВИ дают и в МГУ, от 80.")],
        ]
    )
    case = evaluate.parse_case(
        {
            "id": "x",
            "turns": ["Хочу в ВШЭ на ПМИ", "А какой балл ЕГЭ?"],
            "max_tools": 0,
            "must_mention_conditions": ["85"],
        }
    )
    outcome = await evaluate.run_case(case, fake, None, vocab)
    # выдумки не дошли до ученика: повтор тоже с ними, поэтому предложение вырезано
    second = outcome.turns[1]
    assert "«МГУ»" in fake.requests[-1]["messages"][-1]["content"]
    assert second.answer == f"Нужен ЕГЭ от 85.\n\n{CUT_NOTE}"
    assert outcome.violations == []
    assert outcome.conditions_named is True
    assert any("вызовов инструментов 1 > 0" in reason for reason in outcome.reasons)


async def test_dialog_stops_after_error(vocab: Vocabulary) -> None:
    fake = FakeProvider([[]])  # пустой ответ модели
    case = evaluate.parse_case({"id": "x", "turns": ["а", "б"]})
    outcome = await evaluate.run_case(case, fake, None, vocab)
    assert len(outcome.turns) == 1
    assert outcome.reasons == ["реплика 1: ошибка: empty"]
    assert not outcome.passed and not outcome.answered


async def test_report_summary_and_compare(vocab: Vocabulary, fake_tools: list[str]) -> None:
    fake = FakeProvider([[TextDelta("Привет! Чем увлекаешься?")], [TextDelta("Нет данных.")]])
    cases = [
        evaluate.Case.single("a", "Привет", include=["?"]),
        evaluate.Case.single("b", "Что такое X?", include=["есть"]),
    ]
    outcomes = [await evaluate.run_case(case, fake, None, vocab) for case in cases]
    data = evaluate.report(outcomes, "fake")
    summary = data["summary"]
    assert (summary["cases"], summary["passed"], summary["no_fabrication_share"]) == (2, 1, 1.0)
    assert summary["conditions_share"] is None and summary["dialogs_passed_share"] is None
    assert summary["first_delta_p50"] is not None and summary["rounds_mean"] == 1
    json.dumps(data, ensure_ascii=False)  # отчёт сохраняется в JSON

    better = json.loads(json.dumps(data))
    better["summary"]["passed_share"] = 1.0
    better["cases"][1]["passed"] = True
    lines = evaluate.compare(data, better)
    assert "  пройдено: 0.50 → 1.00 (+0.50)" in lines
    assert "  b: стал проходить" in lines


def test_percentile() -> None:
    assert evaluate.percentile([], 0.5) is None
    assert evaluate.percentile([3.0, 1.0, 2.0], 0.5) == 2.0
    assert evaluate.percentile([float(i) for i in range(1, 21)], 0.95) == 19.0
