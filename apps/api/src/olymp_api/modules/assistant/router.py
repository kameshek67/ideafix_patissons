import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from olymp_api import errors
from olymp_api.max_auth import HEADER, InitDataError, validate_init_data
from olymp_api.modules.achievements.service import parse_specs
from olymp_api.redis_support import hit

from .schemas import AssistantConfig, AssistantStreamEvent, ChatRequest, FeedbackRequest
from .service import SUGGESTIONS, conversation
from .tools import ToolContext

router = APIRouter(prefix="/assistant", tags=["assistant"])

DAY = 86_400
MINUTE = 60


def client_key(request: Request) -> str:
    """Лимит считаем на пользователя MAX, если его подпись верна, иначе на IP."""
    settings = request.app.state.settings
    init_data = request.headers.get(HEADER, "")
    if init_data and settings.max_bot_token:
        try:
            user = validate_init_data(init_data, settings.max_bot_token, settings.max_init_data_ttl)
            return f"max:{user.id}"
        except InitDataError:
            pass
    return f"ip:{request.client.host if request.client else 'unknown'}"


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/config", response_model=AssistantConfig)
async def config(request: Request) -> Any:
    """Доступен ли помощник. Без настроек LLM кнопка на сайте скрыта."""
    provider = request.app.state.llm
    enabled = provider is not None and request.app.state.session_factory is not None
    return {
        "enabled": enabled,
        "model_label": provider.model_label if enabled else None,
        "suggestions": SUGGESTIONS,
    }


@router.post(
    "/chat",
    response_class=StreamingResponse,
    responses={
        200: {
            "model": AssistantStreamEvent,
            "description": "Поток text/event-stream: status, delta, entities, sources, done, error",
        }
    },
)
async def chat(body: ChatRequest, request: Request) -> Response:
    """Ответ помощника потоком. История хранится на клиенте, сервер её не сохраняет."""
    provider = request.app.state.llm
    factory = request.app.state.session_factory
    if provider is None or factory is None:
        raise HTTPException(503, "Помощник выключен")
    parse_specs(body.diplomas)  # неверный диплом — ошибка запроса, а не сбой внутри потока

    settings = request.app.state.settings
    who = client_key(request)
    for window, limit in (
        (MINUTE, settings.assistant_rate_per_minute),
        (DAY, settings.assistant_rate_per_day),
    ):
        if not limit:
            continue
        count, retry = await hit(request, f"assistant:{window}:{who}", window)
        if count > limit:
            response = errors.problem(request, 429, "Слишком много сообщений")
            response.headers["Retry-After"] = str(retry)
            return response

    async def spend() -> bool:
        limit = settings.llm_daily_requests
        if not limit:
            return True
        count, _ = await hit(request, "assistant:llm", DAY)
        return bool(count <= limit)

    async def stream() -> AsyncIterator[str]:
        # сессия живёт внутри генератора: зависимости FastAPI могут закрыться раньше потока
        async with factory() as session:
            ctx = ToolContext(session, body.diplomas)
            async for event, data in conversation(provider, body.messages, ctx, spend):
                yield sse(event, data)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/feedback", status_code=204)
async def feedback(body: FeedbackRequest, request: Request) -> Response:
    """Оценка ответа: только счётчик в метриках, текст ответа не сохраняется."""
    request.app.state.assistant_feedback.labels("up" if body.rating > 0 else "down").inc()
    return Response(status_code=204)
