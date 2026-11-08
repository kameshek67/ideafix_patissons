"""«Мои дипломы»: где дипломы ученика дают льготы, и хранение дипломов пользователя MAX.

Строки льгот берутся теми же связями «льгота — олимпиада — профиль», что и в обратном
поиске, а условия вуза (кому, класс, годы, предмет) проверяет olymp_domain.diplomas.
"""

from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from olymp_domain.diplomas import (
    CAMPAIGN_YEAR,
    DIPLOMA_YEARS,
    MAX_DIPLOMAS,
    Diploma,
    DiplomaSpec,
    Fit,
    Link,
    Reject,
    better,
    is_real_profile,
    match,
    profile_keys,
)
from olymp_domain.ege import EgeRequirement, EgeStatus, ege_status, subject_of_profile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import Row, fetch_all, fetch_one
from olymp_api.max_auth import MaxUser
from olymp_api.olympiads import BENEFIT_FIELDS, BENEFIT_ORDER, serialize_benefit
from olymp_api.universities import UNIVERSITY_FIELDS, university_of

TYPE_RANK = {t: i for i, t in enumerate(BENEFIT_ORDER)}
# порядок строк в таблице вуза: БВИ, 100 баллов, остальное
TYPE_SQL = """CASE b.benefit_type WHEN 'БВИ' THEN 0 WHEN '100 баллов' THEN 1
                                  WHEN 'Особое право (БВИ/100)' THEN 2 ELSE 3 END"""


def parse_specs(values: list[str]) -> list[DiplomaSpec]:
    """Строки дипломов из запроса; повторы убираются, порядок сохраняется."""
    if len(values) > MAX_DIPLOMAS:
        raise HTTPException(422, f"Не больше {MAX_DIPLOMAS} дипломов")
    specs: list[DiplomaSpec] = []
    for value in values:
        if len(value) > 300:
            raise HTTPException(422, "Слишком длинная строка диплома")
        try:
            spec = DiplomaSpec.parse(value)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if spec not in specs:
            specs.append(spec)
    return specs


# ---------------------------------------------------------------- справочник для формы


def olympiad_of(row: Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "key": row["key"],
        "short_name": row["short_name"],
        "canonical_name": row["canonical_name"],
    }


def profile_of(row: Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "key": row["key"],
        "name": row["name"],
        "level": row["level"],
        "mentions": row["mentions"],
    }


async def diploma_form(session: AsyncSession, olympiad_id: int) -> dict[str, Any]:
    olympiad = await fetch_one(
        session,
        """SELECT id, squash_key AS key, short_name, canonical_name
           FROM olympiads WHERE id = :id""",
        {"id": olympiad_id},
    )
    if not olympiad:
        raise HTTPException(404, "Олимпиада не найдена")
    profiles = await fetch_all(
        session,
        """SELECT id, squash_key AS key, name, level, mentions FROM olympiad_profiles
           WHERE olympiad_id = :id ORDER BY mentions DESC, name, id""",
        {"id": olympiad_id},
    )
    return {
        "olympiad": olympiad_of(olympiad),
        "profiles": [profile_of(p) for p in profiles if is_real_profile(p["name"])],
    }


# ---------------------------------------------------------------- дипломы -> текущая база


@dataclass
class Resolved:
    spec: DiplomaSpec
    olympiad: Row | None
    profile: Row | None

    @property
    def found(self) -> bool:
        return self.olympiad is not None and (
            self.spec.profile_key is None or self.profile is not None
        )

    def diploma(self) -> Diploma | None:
        if not self.found or self.olympiad is None:
            return None
        return Diploma(
            olympiad_id=self.olympiad["id"],
            profile_id=self.profile["id"] if self.profile else None,
            profile_keys=profile_keys(self.profile["name"]) if self.profile else frozenset(),
            role=self.spec.role,
            grade=self.spec.grade,
            year=self.spec.year,
        )


async def resolve(session: AsyncSession, specs: list[DiplomaSpec]) -> list[Resolved]:
    """Ключи олимпиад и профилей из строк дипломов -> строки текущей базы."""
    keys = sorted({s.olympiad_key for s in specs})
    olympiads = {
        row["key"]: row
        for row in await fetch_all(
            session,
            """SELECT id, squash_key AS key, short_name, canonical_name
               FROM olympiads WHERE squash_key = ANY(:keys)""",
            {"keys": keys},
        )
    }
    ids = sorted(o["id"] for o in olympiads.values())
    profiles = {
        (row["olympiad_id"], row["key"]): row
        for row in await fetch_all(
            session,
            """SELECT id, olympiad_id, squash_key AS key, name, level, mentions
               FROM olympiad_profiles WHERE olympiad_id = ANY(:ids)""",
            {"ids": ids},
        )
    }
    out = []
    for spec in specs:
        olympiad = olympiads.get(spec.olympiad_key)
        profile = (
            profiles.get((olympiad["id"], spec.profile_key))
            if olympiad and spec.profile_key
            else None
        )
        out.append(Resolved(spec, olympiad, profile))
    return out


# ---------------------------------------------------------------- подбор льгот


@dataclass
class Matched:
    """Льгота, которую дают дипломы."""

    benefit_type: str
    program_id: int
    university_id: int
    fit: Fit
    diplomas: set[int] = field(default_factory=set)


@dataclass
class ProgramBest:
    university_id: int
    rank: int
    # хотя бы одна строка подошла уверенно (профиль или предмет совпали)
    sure: bool


def program_best(
    matched: dict[int, Matched], only: set[int] | None = None
) -> dict[int, ProgramBest]:
    """Лучшая льгота каждого направления: БВИ лучше 100 баллов, те — остальных."""
    best: dict[int, ProgramBest] = {}
    for benefit_id, m in matched.items():
        if only is not None and benefit_id not in only:
            continue
        rank = TYPE_RANK.get(m.benefit_type, len(TYPE_RANK))
        current = best.get(m.program_id)
        if current is None:
            best[m.program_id] = ProgramBest(m.university_id, rank, m.fit is not Fit.CHECK)
        else:
            current.rank = min(current.rank, rank)
            current.sure = current.sure or m.fit is not Fit.CHECK
    return best


def counts(best: dict[int, ProgramBest]) -> dict[str, int]:
    return {
        "universities": len({p.university_id for p in best.values()}),
        "programs": len(best),
        "bvi": sum(1 for p in best.values() if p.rank == 0),
        "sto": sum(1 for p in best.values() if p.rank == 1),
        "other": sum(1 for p in best.values() if p.rank > 1),
    }


# отметка «не хватает до N баллов» в итогах (F-03)
CLOSE_GAP = 5


def ege_statuses(
    best_link: dict[int, Row], scores: dict[str, int]
) -> dict[int, tuple[EgeStatus, int | None, tuple[str, ...]]]:
    """Статус подтверждения ЕГЭ каждой подходящей льготы по колонкам, разобранным при сборке
    (T-031). Предмет не указан — по профилю олимпиады, через которую льгота подошла."""
    return {
        benefit_id: ege_status(
            None
            if row["confirm_subjects"] is None  # текст не разобран
            else EgeRequirement(tuple(row["confirm_subjects"]), row["min_ege_score"]),
            scores,
            subject_of_profile(row["link_profile"]),
        )
        for benefit_id, row in best_link.items()
    }


def ege_summary(
    matched: dict[int, "Matched"],
    statuses: dict[int, tuple[EgeStatus, int | None, tuple[str, ...]]],
) -> tuple[dict[str, Any], dict[int, int]]:
    """Итоги подтверждения баллами и число подтверждённых направлений по вузам."""
    confirmed_programs: dict[int, int] = {}  # направление → вуз
    close: set[int] = set()
    by_status = {"confirmed": 0, "short": 0, "missing_score": 0, "no_threshold": 0}
    for benefit_id, (status, gap, _) in statuses.items():
        m = matched[benefit_id]
        by_status[status] += 1
        if status == "confirmed":
            confirmed_programs[m.program_id] = m.university_id
        elif status == "short" and gap is not None and gap <= CLOSE_GAP:
            close.add(m.university_id)
    per_university: dict[int, int] = {}
    for uid in confirmed_programs.values():
        per_university[uid] = per_university.get(uid, 0) + 1
    summary = {
        "confirmed_programs": len(confirmed_programs),
        "confirmed_universities": len(per_university),
        "close_universities": len(close - per_university.keys()),
        "statuses": by_status,
    }
    return summary, per_university


async def match_diplomas(
    session: AsyncSession,
    specs: list[DiplomaSpec],
    benefit_type: str | None,
    university_id: int | None,
    ege: dict[str, int] | None = None,
) -> dict[str, Any]:
    resolved = await resolve(session, specs)
    diplomas = [r.diploma() for r in resolved]
    olympiad_ids = sorted({d.olympiad_id for d in diplomas if d})

    params: dict[str, Any] = {"ids": olympiad_ids}
    where = ["bo.olympiad_id = ANY(:ids)", "b.layer <> 'raw'"]
    if benefit_type and benefit_type != "Все":
        where.append("b.benefit_type = :benefit_type")
        params["benefit_type"] = benefit_type
    links = await fetch_all(
        session,
        f"""SELECT bo.benefit_id, bo.olympiad_id, bo.profile_id,
                   COALESCE(NULLIF(bo.winner_role, ''), b.winner_role) AS role,
                   b.grade, b.years, b.olympiad_subject AS subject, b.benefit_type,
                   b.confirm_subjects, b.min_ege_score, b.program_id, p.university_id,
                   COALESCE(pr.name, bo.profile) AS link_profile, bo.level AS link_level,
                   bo.matched_via
            FROM benefit_olympiads bo
            JOIN benefits b ON b.id = bo.benefit_id
            JOIN programs p ON p.id = b.program_id
            LEFT JOIN olympiad_profiles pr ON pr.id = bo.profile_id
            WHERE {" AND ".join(where)}
            ORDER BY bo.benefit_id, bo.id""",
        params,
    )

    matched: dict[int, Matched] = {}
    # через какую связь строка подошла лучше всего — для колонки «Профиль в правилах»
    best_link: dict[int, Row] = {}
    rejected: dict[Reject, set[int]] = {reason: set() for reason in Reject}
    per_diploma: list[set[int]] = [set() for _ in diplomas]
    for row in links:
        link = Link(
            olympiad_id=row["olympiad_id"],
            profile_id=row["profile_id"],
            subject=row["subject"],
            role=row["role"],
            grade=row["grade"],
            years=row["years"],
        )
        benefit_id = row["benefit_id"]
        for index, diploma in enumerate(diplomas):
            if diploma is None or diploma.olympiad_id != link.olympiad_id:
                continue
            result = match(diploma, link)
            if isinstance(result, Reject):
                rejected[result].add(benefit_id)
                continue
            entry = matched.get(benefit_id)
            if entry is None:
                entry = matched[benefit_id] = Matched(
                    row["benefit_type"], row["program_id"], row["university_id"], result
                )
                best_link[benefit_id] = row
            elif better(entry.fit, result) is not entry.fit:
                entry.fit = result
                best_link[benefit_id] = row
            entry.diplomas.add(index)
            per_diploma[index].add(benefit_id)

    best = program_best(matched)
    universities: dict[int, dict[str, int]] = {}
    for program in best.values():
        u = universities.setdefault(
            program.university_id, {"programs": 0, "bvi": 0, "sto": 0, "other": 0, "check": 0}
        )
        u["programs"] += 1
        u["bvi" if program.rank == 0 else "sto" if program.rank == 1 else "other"] += 1
        if not program.sure:
            u["check"] += 1

    info = {
        row["university_id"]: row
        for row in await fetch_all(
            session,
            f"SELECT {UNIVERSITY_FIELDS} FROM universities u WHERE u.id = ANY(:ids)",
            {"ids": sorted(universities)},
        )
    }
    # вузы с БВИ — выше; дальше по числу направлений со 100 баллами и прочими льготами
    order = sorted(
        universities,
        key=lambda uid: (
            -universities[uid]["bvi"],
            -universities[uid]["sto"],
            -universities[uid]["other"],
            info[uid]["university"],
        ),
    )
    statuses = ege_statuses(best_link, ege) if ege else {}
    summary, confirmed = ege_summary(matched, statuses) if ege else (None, {})
    results: list[dict[str, Any]] = [
        {
            "university": university_of(info[uid]),
            **universities[uid],
            **({"ege_confirmed": confirmed.get(uid, 0)} if ege else {}),
        }
        for uid in order
    ]

    out: dict[str, Any] = {
        "diplomas": [
            {
                "spec": str(r.spec),
                "found": r.found,
                "olympiad": olympiad_of(r.olympiad) if r.olympiad else None,
                "profile": profile_of(r.profile) if r.profile else None,
                "role": r.spec.role.value,
                "grade": r.spec.grade,
                "year": r.spec.year,
                "expired": r.spec.expired,
                "counts": counts(program_best(matched, per_diploma[i])),
            }
            for i, r in enumerate(resolved)
        ],
        "totals": counts(best),
        # строка не считается отклонённой, если её дал другой диплом
        "rejected": {
            reason.value: len(ids - matched.keys())
            for reason, ids in rejected.items()
            if reason is not Reject.PROFILE
        },
        "results": results,
        "ege": summary,
        "campaign_year": CAMPAIGN_YEAR,
        "valid_years": list(DIPLOMA_YEARS),
    }
    if university_id is not None:
        out.update(
            await university_rows(session, university_id, matched, best_link, resolved, statuses)
        )
    return out


async def university_rows(
    session: AsyncSession,
    university_id: int,
    matched: dict[int, Matched],
    best_link: dict[int, Row],
    resolved: list[Resolved],
    statuses: dict[int, tuple[EgeStatus, int | None, tuple[str, ...]]],
) -> dict[str, Any]:
    university = await fetch_one(
        session,
        f"SELECT {UNIVERSITY_FIELDS} FROM universities u WHERE u.id = :id",
        {"id": university_id},
    )
    if not university:
        raise HTTPException(404, "Вуз не найден")
    ids = sorted(bid for bid, m in matched.items() if m.university_id == university_id)
    rows = await fetch_all(
        session,
        f"""SELECT {BENEFIT_FIELDS}, p.id AS program_id, p.faculty_or_direction,
                   p.profile_name, p.code
            FROM benefits b JOIN programs p ON p.id = b.program_id
            WHERE b.id = ANY(:ids)
            ORDER BY p.sort_order, p.id, {TYPE_SQL}, b.id""",
        {"ids": ids},
    )
    olympiads = {
        r.olympiad["id"]: {"id": r.olympiad["id"], "short_name": r.olympiad["short_name"]}
        for r in resolved
        if r.olympiad
    }
    out = []
    for row in rows:
        m = matched[row["id"]]
        link = best_link[row["id"]]
        benefit = serialize_benefit(row, [olympiads[link["olympiad_id"]]])
        benefit["matched"] = {
            "profile": link["link_profile"],
            "profile_id": link["profile_id"],
            "level": link["link_level"],
            "role": link["role"],
            "via": link["matched_via"],
        }
        out.append(
            {
                "program": {
                    "id": row["program_id"],
                    "faculty_or_direction": row["faculty_or_direction"],
                    "profile_name": row["profile_name"],
                    "code": row["code"],
                },
                "benefit": benefit,
                "diplomas": sorted(m.diplomas),
                "fit": m.fit.value,
                **(
                    {
                        "ege_status": statuses[row["id"]][0],
                        "ege_gap": statuses[row["id"]][1],
                        "ege_subjects": list(statuses[row["id"]][2]),
                    }
                    if row["id"] in statuses
                    else {}
                ),
            }
        )
    return {"university": university_of(university), "rows": out}


# ---------------------------------------------------------------- дипломы пользователя MAX


async def touch_user(session: AsyncSession, user: MaxUser) -> None:
    """Запоминает пользователя MAX (имя из initData могло измениться)."""
    await session.execute(
        text(
            """INSERT INTO max_users (id, first_name, last_name, username, language_code,
                                      photo_url)
               VALUES (:id, :first_name, :last_name, :username, :language_code, :photo_url)
               ON CONFLICT (id) DO UPDATE SET
                   first_name = EXCLUDED.first_name, last_name = EXCLUDED.last_name,
                   username = EXCLUDED.username, language_code = EXCLUDED.language_code,
                   photo_url = EXCLUDED.photo_url, seen_at = now()"""
        ),
        {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
            "language_code": user.language_code,
            "photo_url": user.photo_url,
        },
    )


def profile_out(user: MaxUser) -> dict[str, Any]:
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": user.username,
        "photo_url": user.photo_url,
    }


async def saved_diplomas(session: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    rows = await fetch_all(
        session,
        """SELECT olympiad_key, profile_key, role, grade, year, olympiad_name, profile_name
           FROM user_diplomas WHERE user_id = :uid ORDER BY position""",
        {"uid": user_id},
    )
    return [
        {
            "spec": ".".join(
                [
                    r["olympiad_key"],
                    r["profile_key"] or "-",
                    r["role"],
                    str(r["grade"] or 0),
                    str(r["year"] or 0),
                ]
            ),
            "olympiad_name": r["olympiad_name"],
            "profile_name": r["profile_name"],
        }
        for r in rows
    ]


async def saved_ege(session: AsyncSession, user_id: int) -> dict[str, Any]:
    rows = await fetch_all(
        session,
        "SELECT subject, score, is_mock FROM user_ege_scores WHERE user_id = :uid ORDER BY subject",
        {"uid": user_id},
    )
    return {
        "ege": {r["subject"]: r["score"] for r in rows},
        "ege_is_mock": any(r["is_mock"] for r in rows),
    }


async def save_ege(
    session: AsyncSession, user_id: int, scores: dict[str, int], is_mock: bool
) -> None:
    await session.execute(
        text("DELETE FROM user_ege_scores WHERE user_id = :uid"), {"uid": user_id}
    )
    if scores:
        await session.execute(
            text(
                """INSERT INTO user_ege_scores (user_id, subject, score, is_mock)
                   VALUES (:uid, :subject, :score, :mock)"""
            ),
            [
                {"uid": user_id, "subject": subject, "score": score, "mock": is_mock}
                for subject, score in scores.items()
            ],
        )


async def my_diplomas(session: AsyncSession, user: MaxUser) -> dict[str, Any]:
    await touch_user(session, user)
    await session.commit()
    return {
        "user": profile_out(user),
        "diplomas": await saved_diplomas(session, user.id),
        **await saved_ege(session, user.id),
    }


async def save_my_diplomas(
    session: AsyncSession,
    user: MaxUser,
    specs: list[DiplomaSpec],
    ege: dict[str, int] | None = None,
    ege_is_mock: bool = False,
) -> dict[str, Any]:
    """Заменяет список дипломов пользователя целиком (последняя запись побеждает)."""
    resolved = await resolve(session, specs)
    # олимпиада могла уйти из базы после обновления данных — названия берём из старой записи
    previous = {d["spec"]: d for d in await saved_diplomas(session, user.id)}

    def names(r: Resolved) -> tuple[str, str]:
        old = previous.get(str(r.spec), {})
        return (
            r.olympiad["short_name"] if r.olympiad else old.get("olympiad_name", ""),
            r.profile["name"] if r.profile else old.get("profile_name", ""),
        )

    # upsert блокирует строку пользователя до коммита: сохранения с двух устройств идут по
    # очереди, и DELETE+INSERT не упирается в уникальный (user_id, position). Не переносить ниже.
    await touch_user(session, user)
    await session.execute(text("DELETE FROM user_diplomas WHERE user_id = :uid"), {"uid": user.id})
    if resolved:
        await session.execute(
            text(
                """INSERT INTO user_diplomas (user_id, position, olympiad_key, profile_key, role,
                                              grade, year, olympiad_name, profile_name)
                   VALUES (:uid, :position, :olympiad_key, :profile_key, :role, :grade, :year,
                           :olympiad_name, :profile_name)"""
            ),
            [
                {
                    "uid": user.id,
                    "position": position,
                    "olympiad_key": r.spec.olympiad_key,
                    "profile_key": r.spec.profile_key,
                    "role": r.spec.role.value,
                    "grade": r.spec.grade,
                    "year": r.spec.year,
                    "olympiad_name": names(r)[0],
                    "profile_name": names(r)[1],
                }
                for position, r in enumerate(resolved)
            ],
        )
    if ege is not None:  # None — старый клиент, баллы не трогаем
        await save_ege(session, user.id, ege, ege_is_mock)
    await session.commit()
    return {
        "user": profile_out(user),
        "diplomas": await saved_diplomas(session, user.id),
        **await saved_ege(session, user.id),
    }
