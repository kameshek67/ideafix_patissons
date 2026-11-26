from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from olymp_api.schemas import ResponseModel


class SourceIn(BaseModel):
    """Ссылка на страницу или документ вуза, которую нужно разобрать."""

    url: str = Field(min_length=8, max_length=2000)
    university: str = Field(min_length=2, max_length=300)


class SourceCreated(ResponseModel):
    source_id: int
    job_id: int
    # false — по этой ссылке уже идёт разбор, вернулась существующая задача
    created: bool


class SourceOut(ResponseModel):
    id: int
    university: str
    url: str
    kind: str
    created_at: datetime
    last_checked_at: datetime | None
    last_job_id: int | None
    last_job_status: str | None


class JobOut(ResponseModel):
    id: int
    source_id: int
    university: str
    url: str
    status: str
    # причина ошибки простыми словами; пусто, если ошибки нет
    error: str
    records_count: int
    quotes_checked: int
    quotes_found: int
    # принято, но база ещё не пересобрана
    rebuild_needed: bool
    created_at: datetime
    updated_at: datetime


class JobDetail(JobOut):
    """Задача с найденными документами и разницей с текущими строками вуза."""

    documents: list[dict[str, Any]]
    # added, removed, changed, same и examples: до 5 примеров каждого вида с цитатами
    diff: dict[str, Any]


class JobDecision(ResponseModel):
    id: int
    status: str
    records: int
