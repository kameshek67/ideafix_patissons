from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.clients import client_key
from olymp_api.db import get_session
from olymp_api.redis_support import hit

from . import service
from .schemas import ReportCreated, ReportIn

router = APIRouter(tags=["reports"])


async def limit_reports(request: Request) -> None:
    """С одного посетителя — несколько сообщений в час, всего — потолок в сутки."""
    settings = request.app.state.settings
    for key, window, limit in (
        (f"reports:{client_key(request)}", 3600, settings.report_rate_limit),
        ("reports:all", 86400, settings.report_daily_limit),
    ):
        if not limit:
            continue
        count, retry = await hit(request, key, window)
        if count > limit:
            raise HTTPException(
                429, "Слишком много сообщений, попробуй позже", headers={"Retry-After": str(retry)}
            )


@router.post("/reports", response_model=ReportCreated, status_code=201)
async def create_report(
    request: Request, body: ReportIn, session: AsyncSession = Depends(get_session)
) -> Any:
    """Сообщение «Нашли ошибку в данных» к карточке направления или выдаче по олимпиаде.

    Хранится текст и названия того, что было на экране; личные данные не нужны и не
    запрашиваются. Выгрузка для команды — scripts/export_reports.py."""
    await limit_reports(request)
    return {"id": await service.save(session, body)}
