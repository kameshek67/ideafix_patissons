"""Условия льготы в инструментах помощника (F1, F2, D2): строки, расхождения, правила приёма.

Чистые функции проверяются без базы, остальное — на настоящей собранной базе.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from olymp_api.db import fetch_one, make_engine
from olymp_api.modules.assistant import tools
from olymp_api.modules.assistant.conditions import (
    CONFLICT_NOTE,
    DATA_NOTICE,
    Condition,
    diverging,
    summarize,
)
from olymp_api.modules.assistant.tools import MAX_CONDITIONS_BYTES, ToolContext, ToolResult
from olymp_api.settings import Settings
from sqlalchemy.ext.asyncio import AsyncSession


def benefit(**fields: Any) -> dict[str, Any]:
    """Строка льготы в том виде, в каком её отдаёт поиск."""
    base = {
        "benefit_type": "БВИ",
        "olympiad_profile": "математика",
        "winner_role": "",
        "grade": "",
        "confirm_subject": "математика",
        "min_ege": "",
        "award_subject": "",
        "years": "",
        "level": "",
        "derived": False,
    }
    return {**base, **fields}


STRICT = benefit(
    winner_role="только победители", grade="11 класс", min_ege="85 и более"
)  # ПМИ ВШЭ, «Высшая проба», математика
LOOSE = benefit(winner_role="победители и призёры", min_ege="75 и более")


def test_line_has_who_grade_subject_and_threshold() -> None:
    line = Condition.from_benefit(STRICT).line()
    for part in ("БВИ", "математика", "только победители", "11 класс", "ЕГЭ математика ≥ 85"):
        assert part in line


def test_line_marks_derived_and_compacts_years() -> None:
    line = Condition.from_benefit(
        benefit(derived=True, years="2023, 2024, 2025, 2026", min_ege="нет", confirm_subject="")
    ).line()
    assert "[по профилю]" in line
    assert "2023–2026" in line
    assert "порога ЕГЭ в документе нет" in line


def test_100_points_names_exam_subject() -> None:
    line = Condition.from_benefit(benefit(benefit_type="100 баллов", award_subject="физика")).line()
    assert line.startswith("100 баллов (ЕГЭ физика)")


def test_contradiction_is_flagged_not_chosen() -> None:
    summary = summarize([STRICT, LOOSE], cap=5)
    assert summary.conflict
    assert len(summary.lines) == 2
    assert all("расходятся" in line for line in summary.lines)
    assert summary.as_fields()["conflict"] == CONFLICT_NOTE
    joined = " ".join(summary.lines)
    assert "≥ 85" in joined
    assert "≥ 75" in joined


def test_different_grades_or_subjects_are_not_contradictions() -> None:
    ten = benefit(winner_role="победители и призёры", grade="10 класс", min_ege="75")
    eleven = benefit(winner_role="победители и призёры", grade="11 класс", min_ege="75")
    physics = benefit(confirm_subject="физика", min_ege="85")
    assert not diverging(Condition.from_benefit(b) for b in (ten, eleven, physics, LOOSE))
    assert not summarize([ten, eleven, physics], cap=5).conflict


def test_duplicates_collapse_and_cap_reports_the_rest() -> None:
    rows = [LOOSE, dict(LOOSE), benefit(olympiad_profile="физика", confirm_subject="физика")]
    rows.append(benefit(confirm_subject="химия"))
    summary = summarize(rows, cap=2)
    assert len(summary.lines) == 2
    assert summary.more == 1
    assert not summary.conflict


def test_conflicting_lines_survive_the_cap() -> None:
    others = [benefit(confirm_subject=name) for name in ("физика", "химия", "биология")]
    summary = summarize([*others, STRICT, LOOSE], cap=2)
    assert summary.conflict
    assert all("расходятся" in line for line in summary.lines)


# ---------------------------------------------------------------- на собранной базе


@pytest.fixture
async def session(built_database_url: str) -> AsyncIterator[AsyncSession]:
    engine = make_engine(Settings(_env_file=None, database_url=built_database_url))
    assert engine is not None
    async with AsyncSession(engine) as opened:
        yield opened
    await engine.dispose()


async def call(ctx: ToolContext, name: str, **args: Any) -> tuple[dict[str, Any], ToolResult]:
    result = await tools.run_tool(name, json.dumps(args, ensure_ascii=False), ctx)
    return json.loads(result.content), result


async def proba(ctx: ToolContext) -> int:
    found, _ = await call(ctx, "find_olympiads", query="высшая проба")
    return int(found["olympiads"][0]["olympiad_id"])


async def hse_pmi(session: AsyncSession) -> int:
    row = await fetch_one(
        session,
        """SELECT p.id FROM programs p JOIN universities u ON u.id = p.university_id
           WHERE u.short_name = 'НИУ ВШЭ (Москва)' AND p.code = '01.03.02'
                 AND p.faculty_or_direction ILIKE '%Прикладная математика и информатика%'
           ORDER BY p.id LIMIT 1""",
    )
    assert row, "в базе нет ПМИ ВШЭ (Москва)"
    return int(row["id"])


async def test_universities_come_with_conditions(session: AsyncSession) -> None:
    ctx = ToolContext(session=session, diplomas=[])
    olympiad = await proba(ctx)
    result, raw = await call(ctx, "universities_for_olympiad", olympiad_id=olympiad)
    universities = result["universities"]
    assert len(universities) >= 3
    assert result["data_year"] == 2026
    assert result["notice"] == DATA_NOTICE
    for university in universities:
        assert university["benefits"]
        assert len(university["directions"]) <= tools.PROGRAMS_PER_UNIVERSITY
        for group in university["directions"]:
            assert group["programs"]
            assert group["conditions"], "вуз без условий: модель опять ответит «порога нет»"
    lines = [c for u in universities for g in u["directions"] for c in g["conditions"]]
    assert any("ЕГЭ" in line and "≥" in line for line in lines)
    assert len(raw.content.encode()) <= MAX_CONDITIONS_BYTES
    # id вузов и направлений теперь можно передать в benefit_conditions
    assert {u["university_id"] for u in universities} <= ctx.universities
    assert ctx.programs


async def test_pmi_hse_high_sample_conditions(session: AsyncSession) -> None:
    """Вопрос из плана: БВИ за «Высшую пробу» на ПМИ ВШЭ — победители 11 класса, 85 и 90."""
    ctx = ToolContext(session=session, diplomas=[])
    olympiad = await proba(ctx)
    program = await hse_pmi(session)
    ctx.programs.add(program)
    result, raw = await call(ctx, "benefit_conditions", olympiad_id=olympiad, program_id=program)
    assert result["university"] == "НИУ ВШЭ (Москва)"
    content = raw.content
    for part in ("85", "90", "победител", "11 класс"):
        assert part in content, part
    assert "ЕГЭ математика ≥ 85" in content
    assert "ЕГЭ информатика ≥ 90" in content
    assert result["data_year"] == 2026
    [item] = result["programs"]
    assert item["program_id"] == program
    assert item["document"]
    assert raw.sources
    assert all(s["url"].startswith("http") and s["title"] for s in raw.sources)
    assert len(content.encode()) <= MAX_CONDITIONS_BYTES


async def test_benefit_conditions_by_university(session: AsyncSession) -> None:
    ctx = ToolContext(session=session, diplomas=[])
    olympiad = await proba(ctx)
    listed, _ = await call(ctx, "universities_for_olympiad", olympiad_id=olympiad)
    university = listed["universities"][0]["university_id"]
    result, raw = await call(
        ctx, "benefit_conditions", olympiad_id=olympiad, university_id=university
    )
    assert result["programs"]
    assert all(p["conditions"] for p in result["programs"])
    assert len(raw.content.encode()) <= MAX_CONDITIONS_BYTES


async def test_olympiads_for_program_have_conditions(session: AsyncSession) -> None:
    ctx = ToolContext(session=session, diplomas=[])
    result, raw = await call(
        ctx, "olympiads_for_program", university="вшэ", program_query="прикладная"
    )
    assert result["olympiads"]
    assert all(o["conditions"] for o in result["olympiads"])
    assert result["data_year"] == 2026
    assert ctx.programs == {result["program_id"]}
    assert len(raw.content.encode()) <= MAX_CONDITIONS_BYTES
    # условия пары доступны, потому что и олимпиада, и направление пришли из этого же ответа
    pair, _ = await call(
        ctx,
        "benefit_conditions",
        olympiad_id=result["olympiads"][0]["olympiad_id"],
        program_id=result["program_id"],
    )
    assert pair["programs"][0]["conditions"]


async def test_benefit_conditions_rejects_foreign_ids(session: AsyncSession) -> None:
    ctx = ToolContext(session=session, diplomas=[])
    program = await hse_pmi(session)

    unknown_olympiad, _ = await call(ctx, "benefit_conditions", olympiad_id=5, program_id=program)
    assert "find_profiles" in unknown_olympiad["error"]

    olympiad = await proba(ctx)
    foreign_program, _ = await call(
        ctx, "benefit_conditions", olympiad_id=olympiad, program_id=program
    )
    assert "program_id" in foreign_program["error"]

    foreign_university, _ = await call(
        ctx, "benefit_conditions", olympiad_id=olympiad, university_id=1
    )
    assert "university_id" in foreign_university["error"]

    foreign_profile, _ = await call(
        ctx, "benefit_conditions", olympiad_id=olympiad, university_id=1, profile_id=1
    )
    assert "profile_id" in foreign_profile["error"]

    nothing, _ = await call(ctx, "benefit_conditions", olympiad_id=olympiad)
    assert "program_id или university_id" in nothing["error"]

    ctx.programs.add(10**9)
    missing, _ = await call(ctx, "benefit_conditions", olympiad_id=olympiad, program_id=10**9)
    assert "error" in missing


async def test_pair_without_benefits_is_not_no_benefit(session: AsyncSession) -> None:
    ctx = ToolContext(session=session, diplomas=[])
    found, _ = await call(ctx, "find_olympiads", query="всош")
    program = await hse_pmi(session)
    ctx.programs.add(program)
    result, _ = await call(
        ctx,
        "benefit_conditions",
        olympiad_id=found["olympiads"][0]["olympiad_id"],
        program_id=program,
    )
    assert result["data_year"] == 2026
    assert result["programs"] or "не значит" in result["note"]


async def test_explain_rule_diploma_term(session: AsyncSession) -> None:
    ctx = ToolContext(session=session, diplomas=[])
    result, raw = await call(ctx, "explain_rule", topic="сколько действует диплом")
    rule = result["rules"][0]
    assert "4 года" in rule["topic"]
    assert "четыр" in rule["text"]
    assert rule["checked"]
    assert raw.sources
    assert raw.sources[0]["url"].startswith("https://")
    assert "273" in raw.sources[0]["title"]


async def test_explain_rule_unknown_topic_is_not_invented(session: AsyncSession) -> None:
    ctx = ToolContext(session=session, diplomas=[])
    result, raw = await call(ctx, "explain_rule", topic="какая погода в Москве")
    assert result["rules"] == []
    assert "правила приёма вуза" in result["note"]
    assert raw.sources == []
    error, _ = await call(ctx, "explain_rule", topic="")
    assert "error" in error


@pytest.mark.parametrize("query", ["нто", "всош", "ломоносов", "физтех", "высшая проба"])
async def test_condition_results_stay_under_limit(session: AsyncSession, query: str) -> None:
    ctx = ToolContext(session=session, diplomas=[])
    found, _ = await call(ctx, "find_olympiads", query=query)
    olympiad = found["olympiads"][0]["olympiad_id"]
    result, raw = await call(ctx, "universities_for_olympiad", olympiad_id=olympiad)
    assert len(raw.content.encode()) <= MAX_CONDITIONS_BYTES
    assert result["universities"], "после усечения должен остаться хотя бы один вуз с условиями"
    assert result["universities"][0]["directions"][0]["conditions"]
