from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from olymp_api.schemas import ResponseModel

Message = Annotated[str, Field(min_length=5, max_length=1000)]

# причины жалобы на строку льготы: что именно не совпало с документом
BenefitReason = Literal[
    "no_benefit",  # льготы нет в документе
    "wrong_type",  # другой тип: БВИ вместо 100 баллов или наоборот
    "winners_only",  # только для победителей
    "wrong_grade_or_level",  # другой класс или уровень
    "wrong_ege",  # другой порог ЕГЭ
    "broken_link",  # ссылка на документ не открывается
    "other",
]


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


class BenefitReportIn(BaseModel):
    """«Не совпадает с документом» у строки льготы. Вуз, направление, олимпиаду и условия
    сервер берёт из базы по ключу строки, от клиента нужны только причина и пояснения."""

    kind: Literal["benefit"]
    row_key: Annotated[str, Field(min_length=1, max_length=64)]
    reason: BenefitReason
    message: Annotated[str, Field(max_length=1000)] = ""
    link: Annotated[str, Field(max_length=500)] = ""

    @field_validator("link")
    @classmethod
    def link_is_http(cls, value: str) -> str:
        value = value.strip()
        if value and not value.lower().startswith(("http://", "https://")):
            raise ValueError("ссылка должна начинаться с http:// или https://")
        return value


ReportIn = Annotated[
    ProgramReportIn | OlympiadReportIn | BenefitReportIn, Field(discriminator="kind")
]


class ReportCreated(ResponseModel):
    id: int
