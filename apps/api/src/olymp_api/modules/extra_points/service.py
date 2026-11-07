"""Баллы за индивидуальные достижения: правила вуза из базы + подсчёт движком домена."""

from typing import Any

from fastapi import HTTPException
from olymp_domain.extra_points import Claim, ExtraRule, score
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import Row, fetch_all, fetch_one, scalar

from . import schemas

RULES_SQL = """
SELECT rule_key, kind, label, points, variants, years, recency_years, exclusive_group, notes,
       source_url, source_page, source_quote, review, admission_year
FROM individual_achievements
WHERE university_id = :u AND admission_year = :y
ORDER BY points DESC, rule_key
"""
LIMIT_SQL = """
SELECT max_total, source_url, source_page, source_quote FROM individual_achievement_limits
WHERE university_id = :u AND admission_year = :y
"""


def _source(url: str, page: int | None, quote: str) -> schemas.Source:
    return schemas.Source(url=url, page=page, quote=quote)


def _domain_rule(r: Row) -> ExtraRule:
    return ExtraRule(
        rule_id=r["rule_key"],
        kind=r["kind"],
        points=r["points"],
        admission_year=r["admission_year"],
        variants=tuple(r["variants"]),
        years=tuple(r["years"]),
        recency_years=r["recency_years"],
        exclusive_group=r["exclusive_group"] or None,
        label=r["label"],
        source_url=r["source_url"],
        source_page=r["source_page"],
        source_quote=r["source_quote"],
        review=r["review"],
    )


async def _load(
    session: AsyncSession, university_id: int, year: int
) -> tuple[list[Row], Row | None]:
    if (
        await fetch_one(
            session, "SELECT 1 AS x FROM universities WHERE id = :u", {"u": university_id}
        )
        is None
    ):
        raise HTTPException(404, "Вуз не найден")
    params = {"u": university_id, "y": year}
    return await fetch_all(session, RULES_SQL, params), await fetch_one(session, LIMIT_SQL, params)


async def universities(session: AsyncSession, year: int) -> dict[str, Any]:
    rows = await fetch_all(
        session,
        """SELECT u.id, u.name, u.short_name, COUNT(*) AS rules
           FROM individual_achievements a JOIN universities u ON u.id = a.university_id
           WHERE a.admission_year = :y GROUP BY u.id ORDER BY u.short_name, u.name""",
        {"y": year},
    )
    return {"admission_year": year, "items": rows}


async def rules(session: AsyncSession, university_id: int, year: int) -> dict[str, Any]:
    rows, limit = await _load(session, university_id, year)
    return {
        "university_id": university_id,
        "admission_year": year,
        "max_total": limit["max_total"] if limit else None,
        "max_total_source": (
            _source(limit["source_url"], limit["source_page"], limit["source_quote"])
            if limit
            else None
        ),
        "rules": [
            schemas.ExtraRule(
                id=r["rule_key"],
                kind=r["kind"],
                label=r["label"],
                points=r["points"],
                variants=list(r["variants"]),
                years=list(r["years"]),
                recency_years=r["recency_years"],
                exclusive_group=r["exclusive_group"] or None,
                notes=r["notes"],
                review=r["review"],
                source=_source(r["source_url"], r["source_page"], r["source_quote"]),
            )
            for r in rows
        ],
    }


async def score_claims(session: AsyncSession, req: schemas.ScoreRequest) -> schemas.Score:
    rows, limit = await _load(session, req.university_id, req.admission_year)
    domain = [_domain_rule(r) for r in rows]
    claims = [Claim(c.kind, c.variant, c.year, c.rule_id) for c in req.claims]
    res = score(domain, claims, limit["max_total"] if limit else None)
    return schemas.Score(
        university_id=req.university_id,
        admission_year=req.admission_year,
        status="scored" if domain else "no_data",
        total=res.total,
        raw_total=res.raw_total,
        capped=res.capped,
        max_total=res.max_total,
        awards=[
            schemas.Award(
                rule_id=a.rule.rule_id,
                kind=a.rule.kind,
                label=a.rule.label,
                points=a.rule.points,
                review=a.rule.review,
                source=_source(a.rule.source_url, a.rule.source_page, a.rule.source_quote),
            )
            for a in res.awards
        ],
        skipped=[
            schemas.Skipped(
                rule_id=s.rule.rule_id,
                kind=s.rule.kind,
                label=s.rule.label,
                reason=s.reason.value,
            )
            for s in res.skipped
        ],
        unmatched=[
            schemas.Unmatched(
                kind=c.kind,
                variant=c.variant,
                year=c.year,
                rule_id=c.rule_id,
            )
            for c in res.unmatched
        ],
        unverified=any(a.rule.review != "reviewed" for a in res.awards),
    )


async def data_version(session: AsyncSession) -> str:
    """Версия CSV с баллами за ИД (хэш файлов): входит в ключи кэша вместе со сборкой базы."""
    value = await scalar(session, "SELECT value FROM meta WHERE key = 'extra_points_version'")
    return str(value or "-")
