from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import data_version, get_session
from olymp_api.redis_support import cache_get, cache_set

from . import service
from .schemas import GoalOlympiads

router = APIRouter(prefix="/goals", tags=["goals"])


@router.get("/olympiads", response_model=GoalOlympiads)
async def olympiads(
    request: Request,
    program_id: Annotated[
        list[int],
        Query(min_length=1, max_length=3, description="Направления цели, до трёх"),
    ],
    session: AsyncSession = Depends(get_session),
) -> Any:
    """«Хочу в вуз»: олимпиады с профилями, которые дают БВИ или 100 баллов по выбранным
    направлениям; сначала те, что покрывают больше направлений."""
    ids = list(dict.fromkeys(program_id))
    key = f"v1:goal-olympiads:{await data_version(session)}:{','.join(map(str, ids))}"
    if (hit := await cache_get(request, key)) is not None:
        return hit
    data = GoalOlympiads.model_validate(await service.goal_olympiads(session, ids))
    payload = data.model_dump(mode="json")
    await cache_set(request, key, payload, request.app.state.settings.cache_ttl)
    return payload
