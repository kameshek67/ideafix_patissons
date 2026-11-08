import json
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api import errors
from olymp_api.clients import client_key
from olymp_api.modules.achievements.service import parse_specs
from olymp_api.redis_support import hit

from .context import context_key, decode
from .factcheck import Vocabulary, VocabularyCache
from .schemas import AssistantConfig, AssistantStreamEvent, ChatRequest, FeedbackRequest
from .service import SUGGESTIONS, conversation
from .tools import ToolContext

router = APIRouter(prefix="/assistant", tags=["assistant"])
log = structlog.get_logger()

DAY = 86_400
MINUTE = 60


async def vocabulary(request: Request, session: AsyncSession) -> Vocabulary | None:
    """Словарь вузов и олимпиад для проверки ответа: один на процесс, обновляется после
    пересборки базы. Не загрузился — проверка идёт без словаря (числа и догадки)."""
    cache: VocabularyCache | None = getattr(request.app.state, "assistant_vocabulary", None)
    if cache is None:
        cache = request.app.state.assistant_vocabulary = VocabularyCache()
    try:
        return await cache.get(session)
    except Exception as exc:  # noqa: BLE001 - без словаря ответ всё равно проверяется
        log.warning("assistant_vocabulary_failed", error=type(exc).__name__)
        if session is not None:
            await session.rollback()
        return None


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
            "description": (
                "Поток text/event-stream. Порядок: status (что делает помощник, пока ответа нет; "
                "может быть несколько, последний — «Проверяю ответ…») → delta (ответ кусками, "
                "уже проверенный целиком) → notice (оговорка под ответом, не часть ответа и не "
                "для истории; только если был поиск) → entities → sources → done (message_id и "
                "context для следующего запроса). При сбое — error с code."
            ),
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

    key = context_key(settings.assistant_context_secret)
    dialog = decode(body.context, key)  # неверная подпись — как будто контекста нет

    async def stream() -> AsyncIterator[str]:
        # сессия живёт внутри генератора: зависимости FastAPI могут закрыться раньше потока
        async with factory() as session:
            vocab = await vocabulary(request, session)
            ctx = ToolContext(session, body.diplomas)
            events = conversation(
                provider, body.messages, ctx, spend, key=key, dialog=dialog, vocab=vocab
            )
            async for event, data in events:
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
