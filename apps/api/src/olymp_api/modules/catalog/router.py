from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import data_version, get_session
from olymp_api.redis_support import cache_get, cache_set

from . import service
from .schemas import OlympiadProfiles, Olympiads, Programs, Regions, Stats, Universities

router = APIRouter(tags=["catalog"])


@router.get("/stats", response_model=Stats)
async def stats(request: Request, session: AsyncSession = Depends(get_session)) -> Any:
    """Счётчики для блока «О базе», статистика по вузам, топ олимпиад, отчёт сборки."""
    key = f"v1:stats:{await data_version(session)}"
    if (hit := await cache_get(request, key)) is not None:
        return hit
    data = Stats.model_validate(await service.stats(session)).model_dump(mode="json")
    await cache_set(request, key, data, request.app.state.settings.cache_ttl)
    return data


@router.get("/regions", response_model=Regions)
async def regions(session: AsyncSession = Depends(get_session)) -> Any:
    """Москва / Санкт-Петербург / Регионы."""
    return await service.regions(session)


@router.get("/universities", response_model=Universities)
async def universities(
    region: str | None = Query(None, description="Москва | Санкт-Петербург | Регионы"),
    q: str | None = Query(None, max_length=200),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Вузы с числом направлений и льгот."""
    return await service.universities(session, region, q)


@router.get("/programs", response_model=Programs)
async def programs(
    university_id: int | None = None,
    q: str | None = Query(None, max_length=200),
    limit: int = Query(500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Направления вуза; q ищет по названию, профилю и коду."""
    return await service.programs(session, university_id, q, limit)


@router.get("/olympiads", response_model=Olympiads)
async def olympiads(
    q: str | None = Query(None, max_length=200),
    featured: bool = False,
    limit: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Автокомплит по названиям и сокращениям («всош», «пвг», «вышка»), без q — популярные."""
    return await service.olympiads(session, q, featured, limit)


@router.get("/olympiads/{olympiad_id}/profiles", response_model=OlympiadProfiles)
async def olympiad_profiles(olympiad_id: int, session: AsyncSession = Depends(get_session)) -> Any:
    """Профили олимпиады: у НТО их десятки, и льгота даётся за пару «олимпиада + профиль»."""
    return await service.olympiad_profiles(session, olympiad_id)
