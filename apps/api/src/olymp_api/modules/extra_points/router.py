from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import data_version, get_session
from olymp_api.redis_support import cache_get, cache_set

from . import service
from .schemas import ExtraRules, ExtraUniversities, Score, ScoreRequest

router = APIRouter(tags=["extra-points"])

YEAR = Query(ge=2000, le=2100, description="Год приёмной кампании")


@router.get("/extra-points/universities", response_model=ExtraUniversities)
async def universities(
    request: Request, admission_year: int = YEAR, session: AsyncSession = Depends(get_session)
) -> Any:
    """Вузы, у которых в базе есть баллы за индивидуальные достижения (ГТО, аттестат…)."""
    key = f"v1:extra:unis:{admission_year}:{await data_version(session)}:{await service.data_version(session)}"
    if (hit := await cache_get(request, key)) is not None:
        return hit
    data = ExtraUniversities.model_validate(await service.universities(session, admission_year))
    payload = data.model_dump(mode="json")
    await cache_set(request, key, payload, request.app.state.settings.cache_ttl)
    return payload


@router.get("/extra-points/universities/{university_id}", response_model=ExtraRules)
async def rules(
    request: Request,
    university_id: int,
    admission_year: int = YEAR,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Баллы вуза за достижения и лимит суммы; у каждого правила — цитата из документа вуза."""
    key = f"v1:extra:rules:{university_id}:{admission_year}:{await data_version(session)}:{await service.data_version(session)}"
    if (hit := await cache_get(request, key)) is not None:
        return hit
    data = ExtraRules.model_validate(await service.rules(session, university_id, admission_year))
    payload = data.model_dump(mode="json")
    await cache_set(request, key, payload, request.app.state.settings.cache_ttl)
    return payload


@router.post("/extra-points/score", response_model=Score)
async def score(req: ScoreRequest, session: AsyncSession = Depends(get_session)) -> Score:
    """Сколько баллов за достижения получит школьник в вузе (с лимитом). Данные не сохраняются."""
    return await service.score_claims(session, req)
