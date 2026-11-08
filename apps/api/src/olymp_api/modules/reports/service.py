import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import fetch_one

from .schemas import OlympiadReportIn, ProgramReportIn


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


async def save(session: AsyncSession, body: ProgramReportIn | OlympiadReportIn) -> int:
    context = await context_of(session, body)
    result = await session.execute(
        text(
            """INSERT INTO data_reports (kind, program_id, olympiad_id, university_id, context,
                                         message)
               VALUES (:kind, :program_id, :olympiad_id, :university_id, CAST(:context AS jsonb),
                       :message)
               RETURNING id"""
        ),
        {
            "kind": body.kind,
            "program_id": getattr(body, "program_id", None),
            "olympiad_id": getattr(body, "olympiad_id", None),
            "university_id": getattr(body, "university_id", None),
            "context": json.dumps(context, ensure_ascii=False),
            "message": body.message.strip(),
        },
    )
    report_id = int(result.scalar_one())
    await session.commit()
    return report_id
