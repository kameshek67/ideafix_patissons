from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import data_version, get_session
from olymp_api.redis_support import cache_get, cache_set

from . import service
from .schemas import Quality

router = APIRouter(tags=["quality"])


@router.get("/quality", response_model=Quality)
async def quality(request: Request, session: AsyncSession = Depends(get_session)) -> Any:
    """Насколько можно верить данным: точность извлечения, покрытие базы, жалобы, помощник."""
    key = f"v1:quality:{await data_version(session)}"
    if (hit := await cache_get(request, key)) is not None:
        return hit
    data = Quality.model_validate(await service.quality(session)).model_dump(mode="json")
    await cache_set(request, key, data, request.app.state.settings.cache_ttl)
    return data
