from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.clients import client_key
from olymp_api.db import get_session
from olymp_api.max_auth import optional_max_user_id
from olymp_api.redis_support import hit

from . import service
from .schemas import SuggestionCreated, SuggestionIn

router = APIRouter(tags=["suggestions"])


async def limit_suggestions(request: Request) -> None:
    """С одного посетителя — несколько ссылок в час, всего — потолок в сутки."""
    settings = request.app.state.settings
    for key, window, limit in (
        (f"suggestions:{client_key(request)}", 3600, settings.suggestion_rate_limit),
        ("suggestions:all", 86400, settings.suggestion_daily_limit),
    ):
        if not limit:
            continue
        count, retry = await hit(request, key, window)
        if count > limit:
            raise HTTPException(
                429, "Слишком много ссылок, попробуй позже", headers={"Retry-After": str(retry)}
            )


@router.post("/suggestions", response_model=SuggestionCreated, status_code=201)
async def create_suggestion(
    request: Request, body: SuggestionIn, session: AsyncSession = Depends(get_session)
) -> Any:
    """«Предложить вуз или документ»: ссылка на сайт вуза встаёт в очередь разбора, оператор
    принимает результат вручную. Годится только адрес сайта вуза: домен совпадает с доменом
    известных документов вуза или это .ru / .рф. Списки людей не принимаются; ссылка, которая
    у нас уже есть, возвращает exists. Если запрос из мини-приложения MAX, бот ответит автору,
    когда документ добавят. В ответе только статус."""
    await limit_suggestions(request)
    created = await service.suggest(
        session, body.url, body.university, body.comment, optional_max_user_id(request)
    )
    return {"status": "created" if created else "exists"}
