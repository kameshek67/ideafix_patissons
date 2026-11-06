from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import data_version, get_session
from olymp_api.redis_support import cache_get, cache_set

from . import service
from .schemas import OlympiadSearch, ProgramSearch

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/by-program", response_model=ProgramSearch)
async def by_program(
    request: Request, program_id: int, session: AsyncSession = Depends(get_session)
) -> Any:
    """«Ищу олимпиады под вуз»: строки таблиц по типам льгот, примечания, список олимпиад."""
    key = f"v1:by-program:{await data_version(session)}:{program_id}"
    if (hit := await cache_get(request, key)) is not None:
        return hit
    data = ProgramSearch.model_validate(await service.by_program(session, program_id))
    payload = data.model_dump(mode="json")
    await cache_set(request, key, payload, request.app.state.settings.cache_ttl)
    return payload


@router.get("/by-olympiad", response_model=OlympiadSearch)
async def by_olympiad(
    request: Request,
    q: str = Query(
        ..., min_length=2, max_length=200, description="Название олимпиады или его часть"
    ),
    olympiad_id: int | None = None,
    profile_id: int | None = None,
    university_id: int | None = None,
    region: str | None = None,
    benefit_type: str | None = None,
    limit: int = Query(400, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Обратный поиск «куда поступить с моей олимпиадой»: список вузов, а с university_id —
    все строки выбранного вуза. Точные итоги (total_*) считаются отдельно от лимита выдачи."""
    key = ":".join(
        str(part)
        for part in (
            "v1:by-olympiad",
            await data_version(session),
            q,
            olympiad_id,
            profile_id,
            university_id,
            region,
            benefit_type,
            limit,
        )
    )
    if (hit := await cache_get(request, key)) is not None:
        return hit
    data = OlympiadSearch.model_validate(
        await service.by_olympiad(
            session, q, olympiad_id, profile_id, university_id, region, benefit_type, limit
        )
    )
    payload = data.model_dump(mode="json")
    await cache_set(request, key, payload, request.app.state.settings.cache_ttl)
    return payload
