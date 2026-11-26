from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.clients import client_key
from olymp_api.db import get_session
from olymp_api.max_auth import HEADER, InitDataError, validate_init_data
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


def reporter_id(request: Request) -> int | None:
    """Пользователь MAX по подписанным данным запуска; без них или с чужими — аноним:
    жалоба принимается всегда, просто бот не сможет ответить."""
    settings = request.app.state.settings
    init_data = request.headers.get(HEADER, "")
    if not init_data or not settings.max_bot_token:
        return None
    try:
        return validate_init_data(init_data, settings.max_bot_token, settings.max_init_data_ttl).id
    except InitDataError:
        return None


@router.post("/reports", response_model=ReportCreated, status_code=201)
async def create_report(
    request: Request, body: ReportIn, session: AsyncSession = Depends(get_session)
) -> Any:
    """Сообщение «Нашли ошибку в данных» к карточке направления или выдаче по олимпиаде и
    «Не совпадает с документом» у строки льготы (kind = benefit: ключ строки и причина).

    Хранится текст и названия того, что было на экране; личные данные не нужны и не
    запрашиваются. Если жалоба из мини-приложения MAX, запоминаем id пользователя — бот
    ответит ему, когда оператор проверит. Выгрузка для команды — olymp-export-reports."""
    await limit_reports(request)
    return {"id": await service.save(session, body, reporter_id(request))}
