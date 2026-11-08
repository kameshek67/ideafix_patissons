from typing import Annotated, Literal

from pydantic import BaseModel, Field

from olymp_api.schemas import ResponseModel

Message = Annotated[str, Field(min_length=5, max_length=1000)]


class ProgramReportIn(BaseModel):
    """Ошибка в карточке направления."""

    kind: Literal["program"]
    program_id: int
    message: Message


class OlympiadReportIn(BaseModel):
    """Ошибка в выдаче по олимпиаде в конкретном вузе."""

    kind: Literal["olympiad"]
    olympiad_id: int
    university_id: int | None = None
    message: Message


ReportIn = Annotated[ProgramReportIn | OlympiadReportIn, Field(discriminator="kind")]


class ReportCreated(ResponseModel):
    id: int
