import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import get_session

from . import service
from .schemas import JobDecision, JobDetail, JobOut, SourceCreated, SourceIn, SourceOut


async def require_ops(request: Request) -> None:
    """Оператор приходит с заголовком Authorization: Bearer <OLYMP_OPS_TOKEN>. Токен не задан в
    настройках — раздела как будто нет (404), чтобы публичный стенд его не выдавал."""
    token = request.app.state.settings.ops_token
    if not token:
        raise HTTPException(404, "Not Found")
    scheme, _, given = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        given.strip().encode(), token.encode()
    ):
        raise HTTPException(401, "Нужен токен оператора", headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(prefix="/ops", tags=["ops"], dependencies=[Depends(require_ops)])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/sources", response_model=SourceCreated, status_code=201)
async def add_source(body: SourceIn, session: Session) -> Any:
    """Поставить ссылку на разбор: страница вуза или документ (PDF, xlsx)."""
    source_id, job_id, created = await service.add_source(
        session, body.url, body.university, "ops api"
    )
    return {"source_id": source_id, "job_id": job_id, "created": created}


@router.get("/sources", response_model=list[SourceOut])
async def sources(session: Session) -> Any:
    return await service.list_sources(session)


@router.get("/jobs", response_model=list[JobOut])
async def jobs(
    session: Session,
    status: str | None = Query(
        None, pattern="^(queued|fetching|extracting|review|accepted|rejected|failed)$"
    ),
    origin: str | None = Query(None, pattern="^(operator|user)$"),
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    return await service.list_jobs(session, status, limit, origin)


@router.get("/jobs/{job_id}", response_model=JobDetail)
async def job(job_id: int, session: Session) -> Any:
    """Задача: найденные документы, сколько цитат проверено, разница с базой и примеры."""
    return await service.get_job(session, job_id)


@router.post("/jobs/{job_id}/accept", response_model=JobDecision)
async def accept(job_id: int, session: Session) -> Any:
    """Принять записи: они попадут в базу при ближайшей пересборке (её запускает воркер)."""
    return await service.decide(session, job_id, True)


@router.post("/jobs/{job_id}/reject", response_model=JobDecision)
async def reject(job_id: int, session: Session) -> Any:
    return await service.decide(session, job_id, False)
