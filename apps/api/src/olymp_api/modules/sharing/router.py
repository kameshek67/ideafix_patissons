from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import get_session
from olymp_api.redis_support import hit

from . import service
from .schemas import Share, ShareCreated, ShareIn

router = APIRouter(tags=["sharing"])


async def limit_creation(request: Request) -> None:
    """Лимит на создание ссылок: с одного адреса в минуту и всего за сутки."""
    settings = request.app.state.settings
    ip = request.client.host if request.client else "unknown"
    for key, window, limit in (
        (f"shares:{ip}", 60, settings.share_rate_limit),
        ("shares:all", 86400, settings.share_daily_limit),
    ):
        if not limit:
            continue
        count, retry = await hit(request, key, window)
        if count > limit:
            raise HTTPException(
                429, "Слишком много ссылок, попробуйте позже", headers={"Retry-After": str(retry)}
            )


@router.post(
    "/shares",
    response_model=ShareCreated,
    status_code=201,
    responses={200: {"model": ShareCreated, "description": "Этим экраном уже делились"}},
)
async def create_share(
    request: Request,
    response: Response,
    body: ShareIn,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Ссылка «Поделиться» на карточку направления, выдачу по олимпиаде или итоги дипломов.

    Снимок хранит стабильные ключи, а не id: ссылка открывает тот же экран и после
    пересборки базы. Тот же экран — та же ссылка (200), срок жизни продлевается."""
    await limit_creation(request)
    settings = request.app.state.settings
    kind, payload = await service.snapshot(session, body)
    token, created = await service.save(session, kind, payload, settings.share_ttl_days)
    if not created:
        response.status_code = 200
    max_url = (
        f"https://max.ru/{settings.max_bot_name}?startapp=s_{token}"
        if settings.max_bot_token and settings.max_bot_name
        else None
    )
    return {"token": token, "web_path": f"/s/{token}", "max_url": max_url}


@router.get("/shares/{token}", response_model=Share)
async def open_share(
    token: str = Path(pattern=service.TOKEN_PATTERN),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Что открыть по ссылке: тип экрана, фильтр и актуальные id объектов снимка.
    404 — ссылки нет или она устарела."""
    return await service.open_share(session, token)
