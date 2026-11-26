"""Ошибки в формате RFC 9457 (application/problem+json)."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM = "application/problem+json"


def problem(
    request: Request, status: int, title: str, detail: str | None = None, **extra: object
) -> JSONResponse:
    body = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", None),
        **({"detail": detail} if detail else {}),
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM)


def install(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        response = problem(request, exc.status_code, str(exc.detail))
        # например, Retry-After у 429
        response.headers.update(exc.headers or {})
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # входные значения не возвращаем: в запросе могут оказаться персональные данные
        errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return problem(request, 422, "Validation error", errors=errors)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        if is_db_timeout(exc):
            response = problem(request, 503, "База данных занята, повтори через минуту")
            response.headers["Retry-After"] = "30"
            return response
        return problem(request, 500, "Internal server error")


# SQLSTATE отмены по statement_timeout и по lock_timeout
DB_TIMEOUT_CODES = {"57014", "55P03"}


def is_db_timeout(exc: BaseException) -> bool:
    """Запрос к БД отменён по таймауту (см. db.make_engine): клиенту — 503, а не 500."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if code in DB_TIMEOUT_CODES:
            return True
        current = getattr(current, "orig", None) or current.__cause__
    return False
