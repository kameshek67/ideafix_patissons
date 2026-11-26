import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import fetch_one

from .schemas import BenefitReportIn, OlympiadReportIn, ProgramReportIn

ReportBody = ProgramReportIn | OlympiadReportIn | BenefitReportIn


async def benefit_context(session: AsyncSession, row_key: str) -> tuple[dict[str, Any], int, int]:
    """Строка льготы по ключу: что было на экране и id направления и вуза."""
    row = await fetch_one(
        session,
        """SELECT u.id AS university_id, u.name AS university, p.id AS program_id,
                  p.faculty_or_direction AS program, p.profile_name AS profile, p.code,
                  b.benefit_type, b.olympiad_profile, b.olympiad_subject, b.level,
                  b.winner_role, b.grade, b.confirm_subject, b.min_ege, b.years,
                  b.raw_conditions_text AS text, b.source_title, b.source_url,
                  (SELECT string_agg(o.short_name, '; ' ORDER BY o.mentions DESC, o.id)
                   FROM benefit_olympiads bo JOIN olympiads o ON o.id = bo.olympiad_id
                   WHERE bo.benefit_id = b.id) AS olympiad
           FROM benefits b
           JOIN programs p ON p.id = b.program_id
           JOIN universities u ON u.id = p.university_id
           WHERE b.row_key = :key AND b.layer <> 'raw'
           ORDER BY b.id LIMIT 1""",
        {"key": row_key},
    )
    if row is None:
        raise HTTPException(404, "Строка не найдена: возможно, данные уже обновились")
    context = dict(row)
    university_id = context.pop("university_id")
    program_id = context.pop("program_id")
    context["olympiad"] = context["olympiad"] or ""
    return context, program_id, university_id


async def context_of(
    session: AsyncSession, body: ProgramReportIn | OlympiadReportIn
) -> dict[str, Any]:
    """Названия того, что было на экране: после пересборки базы id будут другими."""
    if isinstance(body, ProgramReportIn):
        row = await fetch_one(
            session,
            """SELECT u.name AS university, p.faculty_or_direction AS program,
                      p.profile_name AS profile, p.code, p.source_url
               FROM programs p JOIN universities u ON u.id = p.university_id
               WHERE p.id = :id""",
            {"id": body.program_id},
        )
        if row is None:
            raise HTTPException(404, "Направление не найдено")
        return dict(row)
    olympiad = await fetch_one(
        session,
        "SELECT short_name AS olympiad FROM olympiads WHERE id = :id",
        {"id": body.olympiad_id},
    )
    if olympiad is None:
        raise HTTPException(404, "Олимпиада не найдена")
    context = dict(olympiad)
    if body.university_id is not None:
        university = await fetch_one(
            session,
            "SELECT name AS university, docs_url FROM universities WHERE id = :id",
            {"id": body.university_id},
        )
        if university is None:
            raise HTTPException(404, "Вуз не найден")
        context.update(university)
    return context


async def save(session: AsyncSession, body: ReportBody, max_user_id: int | None = None) -> int:
    program_id = getattr(body, "program_id", None)
    university_id = getattr(body, "university_id", None)
    if isinstance(body, BenefitReportIn):
        context, program_id, university_id = await benefit_context(session, body.row_key)
    else:
        context = await context_of(session, body)
    result = await session.execute(
        text(
            """INSERT INTO data_reports (kind, program_id, olympiad_id, university_id, context,
                                         message, row_key, reason, link, source, max_user_id)
               VALUES (:kind, :program_id, :olympiad_id, :university_id, CAST(:context AS jsonb),
                       :message, :row_key, :reason, :link, 'user', :max_user_id)
               RETURNING id"""
        ),
        {
            "kind": body.kind,
            "program_id": program_id,
            "olympiad_id": getattr(body, "olympiad_id", None),
            "university_id": university_id,
            "context": json.dumps(context, ensure_ascii=False),
            "message": body.message.strip(),
            "row_key": getattr(body, "row_key", ""),
            "reason": getattr(body, "reason", ""),
            "link": getattr(body, "link", ""),
            "max_user_id": max_user_id,
        },
    )
    report_id = int(result.scalar_one())
    await session.commit()
    return report_id
