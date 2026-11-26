"""Рейтинг олимпиад под цель: льготы выбранных направлений сводятся в пары «олимпиада + профиль»."""

from typing import Any

from fastapi import HTTPException
from olymp_domain.ege import subject_of_profile
from olymp_domain.goals import GoalLink, PairInfo, PairKey, build_goal
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import fetch_all


async def goal_olympiads(session: AsyncSession, program_ids: list[int]) -> dict[str, Any]:
    programs = await fetch_all(
        session,
        """SELECT p.id, p.faculty_or_direction, p.code, u.name AS university,
                  u.short_name AS university_short
           FROM programs p JOIN universities u ON u.id = p.university_id
           WHERE p.id = ANY(:ids)""",
        {"ids": program_ids},
    )
    found = {p["id"]: p for p in programs}
    if any(i not in found for i in program_ids):
        raise HTTPException(status_code=404, detail="Направление не найдено")

    rows = await fetch_all(
        session,
        """SELECT bo.olympiad_id, bo.profile_id, o.short_name, o.canonical_name, o.kind,
                  o.in_rsosh_2026_27, pr.name AS profile_name, bo.profile AS link_profile,
                  pr.level, pr.level_2026_27, b.program_id, b.benefit_type,
                  COALESCE(NULLIF(bo.winner_role, ''), b.winner_role) AS role,
                  b.confirm_subject, b.confirm_subjects, b.min_ege_score
           FROM benefit_olympiads bo
           JOIN benefits b ON b.id = bo.benefit_id
           JOIN olympiads o ON o.id = bo.olympiad_id
           LEFT JOIN olympiad_profiles pr ON pr.id = bo.profile_id
           WHERE b.program_id = ANY(:ids) AND b.layer <> 'raw'
             AND b.benefit_type IN ('БВИ', '100 баллов')""",
        {"ids": program_ids},
    )

    pairs: dict[PairKey, PairInfo] = {}
    meta: dict[PairKey, dict[str, Any]] = {}
    links: list[GoalLink] = []
    for row in rows:
        key: PairKey = (row["olympiad_id"], row["profile_id"])
        if key not in pairs:
            in_rsosh = row["in_rsosh_2026_27"]
            # пара вне перечня: олимпиады нет в перечне или нет её профиля
            in_list = in_rsosh is None or (
                in_rsosh and (row["profile_id"] is None or bool(row["level_2026_27"]))
            )
            pairs[key] = PairInfo(
                olympiad_id=key[0],
                profile_id=key[1],
                name=row["short_name"],
                level=(row["level_2026_27"] or row["level"] or "") if row["profile_id"] else "",
                in_list=bool(in_list),
                kind=row["kind"],
            )
            meta[key] = row
        links.append(
            GoalLink(
                pair=key,
                program_id=row["program_id"],
                benefit_type=row["benefit_type"],
                role=row["role"] or "",
                confirm_subject=row["confirm_subject"] or "",
                min_score=row["min_ege_score"],
                has_subject=bool(row["confirm_subjects"])
                or subject_of_profile(row["profile_name"] or row["link_profile"]) is not None,
            )
        )

    items = []
    for item in build_goal(pairs, links):
        row = meta[item.pair.key]
        items.append(
            {
                "olympiad_id": item.pair.olympiad_id,
                "short_name": row["short_name"],
                "canonical_name": row["canonical_name"],
                "kind": row["kind"],
                "profile_id": item.pair.profile_id,
                "profile_name": row["profile_name"] or "",
                "bvi_programs": item.bvi_programs,
                "hundred_programs": item.hundred_programs,
                "who": item.who,
                "level": item.pair.level,
                "in_list_2026_27": item.pair.in_list,
                "ege_subject": item.ege_subject,
                "ege_min_score": item.ege_min_score,
                "prize_hundred_2027": item.prize_hundred_2027,
            }
        )
    return {"programs": [found[i] for i in program_ids], "items": items}
