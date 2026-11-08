"""REST API «Олимпа»: модульный монолит на FastAPI.

    uvicorn olymp_api.main:app --reload

Публичные эндпоинты — под /v1 (сайт ходит на них через прокси Next.js /api/v1/*),
служебные — /healthz, /readyz, /metrics, документация — /docs.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import errors
from .clients import client_key
from .db import make_engine
from .llm import make_provider
from .metrics import install_metrics
from .redis_support import LocalWindow, hit, make_redis
from .settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )
    app = FastAPI(
        title="Олимп API",
        version="1.0.0",
        description="Двусторонний поиск льгот БВИ и 100 баллов по олимпиадам школьников",
    )
    app.state.settings = settings
    errors.install(app)
    install_metrics(app)
    app.state.redis = make_redis(settings.redis_url)
    app.state.local_window = LocalWindow()
    app.state.llm = make_provider(settings)

    engine = make_engine(settings)
    app.state.engine = engine
    app.state.session_factory = (
        async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession) if engine else None
    )

    # Данные каталога разрешаем читать (GET) с любого origin, как в прототипе. Запись
    # (PUT /v1/me/diplomas) — только с самого сайта: чужой origin не пройдёт проверку CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def rate_limit(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if settings.rate_limit_requests and request.url.path.startswith("/v1/"):
            # пользователь MAX или адрес посетителя, а не адрес прокси (T-065)
            count, retry = await hit(request, client_key(request), settings.rate_limit_window)
            if count > settings.rate_limit_requests:
                resp = errors.problem(request, 429, "Too many requests")
                resp.headers["Retry-After"] = str(retry)
                return resp
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    async def readyz() -> dict[str, str]:
        """Готов, если база доступна и собрана."""
        factory = app.state.session_factory
        if factory is None:
            return {"status": "ready"}
        async with factory() as session:
            built = await session.scalar(text("SELECT value FROM meta WHERE key = 'built_at'"))
        if built is None:
            raise HTTPException(503, "База ещё не собрана: запустите olymp-ingest")
        return {"status": "ready", "built_at": str(built)}

    from .modules.achievements.router import router as achievements_router
    from .modules.assistant.router import router as assistant_router
    from .modules.catalog.router import router as catalog_router
    from .modules.extra_points.router import router as extra_points_router
    from .modules.search.router import router as search_router
    from .modules.sharing.router import router as sharing_router

    for router in (
        catalog_router,
        search_router,
        achievements_router,
        sharing_router,
        extra_points_router,
        assistant_router,
    ):
        app.include_router(router, prefix="/v1")
    return app


app = create_app()
