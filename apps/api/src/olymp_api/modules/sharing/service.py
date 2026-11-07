"""Снимки для ссылок «Поделиться»: из id текущей сборки — стабильные ключи и обратно.

В снимке нет id пользователя и его имени. Названия олимпиад и профилей в снимок дипломов
кладёт сервер из базы: текст от клиента на чужой странице не показывается.
"""

import hashlib
import json
import secrets
import string
from typing import Any

from fastapi import HTTPException
from olymp_domain.diplomas import DiplomaSpec
from olymp_domain.program_key import program_stable_key, university_key, university_of_key
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import Row, fetch_all, fetch_one
from olymp_api.universities import UNIVERSITY_FIELDS, university_of

from .schemas import DiplomasShareIn, OlympiadShareIn, ProgramShareIn

Payload = dict[str, Any]

# 10 символов base62 ≈ 59 бит: перебор не окупается при лимите на создание и открытие
ALPHABET = string.ascii_letters + string.digits
TOKEN_LENGTH = 10
TOKEN_PATTERN = rf"^[A-Za-z0-9]{{{TOKEN_LENGTH}}}$"


def new_token() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(TOKEN_LENGTH))


def payload_hash(kind: str, payload: Payload) -> str:
    """sha256 канонического JSON: одинаковый экран — одна и та же ссылка."""
    canonical = json.dumps(
        {"kind": kind, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------- снимок


async def snapshot(
    session: AsyncSession, body: ProgramShareIn | OlympiadShareIn | DiplomasShareIn
) -> tuple[str, Payload]:
    if isinstance(body, ProgramShareIn):
        return "program", await _program(session, body)
    if isinstance(body, OlympiadShareIn):
        return "olympiad", await _olympiad(session, body)
    return "diplomas", await _diplomas(session, body)


async def _program(session: AsyncSession, body: ProgramShareIn) -> Payload:
    row = await fetch_one(
        session,
        """SELECT p.faculty_or_direction, p.profile_name, p.code, u.name AS university
           FROM programs p JOIN universities u ON u.id = p.university_id
           WHERE p.id = :id""",
        {"id": body.program_id},
    )
    if row is None:
        raise HTTPException(404, "Направление не найдено")
    key = program_stable_key(
        row["university"], row["faculty_or_direction"], row["profile_name"], row["code"]
    )
    return {"program": key, "benefit_type": body.benefit_type}


async def _olympiad(session: AsyncSession, body: OlympiadShareIn) -> Payload:
    olympiad = await fetch_one(
        session, "SELECT squash_key FROM olympiads WHERE id = :id", {"id": body.olympiad_id}
    )
    if olympiad is None:
        raise HTTPException(404, "Олимпиада не найдена")
    profile = None
    if body.profile_id is not None:
        row = await fetch_one(
            session,
            "SELECT squash_key FROM olympiad_profiles WHERE id = :id AND olympiad_id = :oid",
            {"id": body.profile_id, "oid": body.olympiad_id},
        )
        if row is None:
            raise HTTPException(404, "Профиль олимпиады не найден")
        profile = row["squash_key"]
    university = None
    if body.university_id is not None:
        row = await fetch_one(
            session, "SELECT name FROM universities WHERE id = :id", {"id": body.university_id}
        )
        if row is None:
            raise HTTPException(404, "Вуз не найден")
        university = university_key(row["name"])
    return {
        "olympiad": olympiad["squash_key"],
        "profile": profile,
        "university": university,
        "benefit_type": body.benefit_type,
    }


async def _diplomas(session: AsyncSession, body: DiplomasShareIn) -> Payload:
    specs: list[DiplomaSpec] = []
    for value in body.diplomas:
        try:
            spec = DiplomaSpec.parse(value)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if spec not in specs:
            specs.append(spec)
    keys = sorted({s.olympiad_key for s in specs})
    olympiads = {
        r["squash_key"]: r["short_name"]
        for r in await fetch_all(
            session,
            "SELECT squash_key, short_name FROM olympiads WHERE squash_key = ANY(:keys)",
            {"keys": keys},
        )
    }
    if not olympiads:
        raise HTTPException(422, "Олимпиад из этих дипломов нет в базе")
    profiles = {
        (r["olympiad_key"], r["squash_key"]): r["name"]
        for r in await fetch_all(
            session,
            """SELECT o.squash_key AS olympiad_key, pr.squash_key, pr.name
               FROM olympiad_profiles pr JOIN olympiads o ON o.id = pr.olympiad_id
               WHERE o.squash_key = ANY(:keys)""",
            {"keys": keys},
        )
    }
    # диплом, которого нет в текущей базе, остаётся в снимке: получатель увидит то же,
    # что и отправитель («нет в базе»), а названия берутся только из базы
    diplomas = [
        {
            "spec": str(spec),
            "olympiad": olympiads.get(spec.olympiad_key, ""),
            "profile": profiles.get((spec.olympiad_key, spec.profile_key or ""), ""),
        }
        for spec in specs
    ]
    return {"diplomas": diplomas, "benefit_type": body.benefit_type}


# ---------------------------------------------------------------- хранение


async def save(
    session: AsyncSession, kind: str, payload: Payload, ttl_days: int
) -> tuple[str, bool]:
    """Токен ссылки и признак «создана сейчас». Тот же снимок — тот же токен, срок продлевается."""
    digest = payload_hash(kind, payload)
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    await session.execute(text("DELETE FROM share_links WHERE expires_at < now()"))
    for _ in range(3):
        try:
            row = await fetch_one(
                session,
                """INSERT INTO share_links (token, kind, payload, payload_hash, expires_at)
                   VALUES (:token, :kind, CAST(:payload AS jsonb), :hash,
                           now() + make_interval(days => :ttl))
                   ON CONFLICT (payload_hash) DO UPDATE SET expires_at = EXCLUDED.expires_at
                   RETURNING token, (xmax = 0) AS created""",
                {
                    "token": new_token(),
                    "kind": kind,
                    "payload": data,
                    "hash": digest,
                    "ttl": ttl_days,
                },
            )
        except IntegrityError:
            # совпал случайный токен у другого снимка — пробуем ещё раз
            await session.rollback()
            continue
        await session.commit()
        if row is not None:
            return str(row["token"]), bool(row["created"])
    raise HTTPException(503, "Не получилось создать ссылку")


# ---------------------------------------------------------------- открытие


async def _university(session: AsyncSession, key: str) -> Row | None:
    for row in await fetch_all(
        session, f"SELECT {UNIVERSITY_FIELDS} FROM universities u ORDER BY u.id"
    ):
        if university_key(row["university"]) == key:
            return row
    return None


async def _program_id(session: AsyncSession, key: str) -> int | None:
    university = await _university(session, university_of_key(key))
    if university is None:
        return None
    rows = await fetch_all(
        session,
        """SELECT id, faculty_or_direction, profile_name, code FROM programs
           WHERE university_id = :uid ORDER BY sort_order, id""",
        {"uid": university["university_id"]},
    )
    for row in rows:
        own = program_stable_key(
            university["university"], row["faculty_or_direction"], row["profile_name"], row["code"]
        )
        if own == key:
            return int(row["id"])
    return None


async def open_share(session: AsyncSession, token: str) -> dict[str, Any]:
    row = await fetch_one(
        session,
        """UPDATE share_links SET opened_count = opened_count + 1, last_opened = now()
           WHERE token = :token AND expires_at > now()
           RETURNING kind, payload""",
        {"token": token},
    )
    await session.commit()
    if row is None:
        raise HTTPException(404, "Ссылка не найдена или устарела")
    payload: Payload = (
        row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])
    )
    kind = str(row["kind"])
    resolved: dict[str, Any] = {
        "program_id": None,
        "olympiad": None,
        "profile_id": None,
        "university": None,
        "diplomas": [],
    }
    if kind == "program":
        resolved["program_id"] = await _program_id(session, payload["program"])
        found = resolved["program_id"] is not None
    elif kind == "olympiad":
        olympiad = await fetch_one(
            session,
            "SELECT id, short_name FROM olympiads WHERE squash_key = :key ORDER BY id LIMIT 1",
            {"key": payload["olympiad"]},
        )
        if olympiad is not None:
            resolved["olympiad"] = {"id": olympiad["id"], "short_name": olympiad["short_name"]}
            if payload.get("profile"):
                profile = await fetch_one(
                    session,
                    """SELECT id FROM olympiad_profiles
                       WHERE olympiad_id = :oid AND squash_key = :key""",
                    {"oid": olympiad["id"], "key": payload["profile"]},
                )
                resolved["profile_id"] = profile["id"] if profile else None
            if payload.get("university"):
                university = await _university(session, payload["university"])
                resolved["university"] = university_of(university) if university else None
        found = olympiad is not None
    else:
        resolved["diplomas"] = payload["diplomas"]
        found = True
    return {
        "kind": kind,
        "benefit_type": payload.get("benefit_type"),
        "found": found,
        "resolved": resolved,
    }
