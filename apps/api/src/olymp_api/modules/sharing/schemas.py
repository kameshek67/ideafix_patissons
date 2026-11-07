from typing import Annotated, Literal

from pydantic import BaseModel, Field

from olymp_api.schemas import ResponseModel, UniversityInfo

# фильтр по типу льготы, с которым экран открыт у отправителя («Все» — без фильтра)
BenefitType = Literal["БВИ", "100 баллов"]
ShareKind = Literal["program", "olympiad", "diplomas"]


class ProgramShareIn(BaseModel):
    """Карточка направления."""

    kind: Literal["program"]
    program_id: int
    benefit_type: BenefitType | None = None


class OlympiadShareIn(BaseModel):
    """Выдача по олимпиаде; профиль и вуз — если выбраны."""

    kind: Literal["olympiad"]
    olympiad_id: int
    profile_id: int | None = None
    university_id: int | None = None
    benefit_type: BenefitType | None = None


class DiplomasShareIn(BaseModel):
    """Итоги дипломов: строки дипломов, как в /v1/achievements/match."""

    kind: Literal["diplomas"]
    diplomas: list[Annotated[str, Field(max_length=300)]] = Field(min_length=1, max_length=20)
    benefit_type: BenefitType | None = None


ShareIn = Annotated[ProgramShareIn | OlympiadShareIn | DiplomasShareIn, Field(discriminator="kind")]


class ShareCreated(ResponseModel):
    token: str
    # путь ссылки на сайте; адрес сайта клиент берёт свой (location.origin)
    web_path: str
    # ссылка на мини-приложение MAX (startapp=s_<token>), если бот настроен
    max_url: str | None


class SharedOlympiad(ResponseModel):
    id: int
    short_name: str


class SharedDiploma(ResponseModel):
    spec: str
    # названия на момент «Поделиться» — из базы, не от клиента
    olympiad: str
    profile: str


class ShareResolved(ResponseModel):
    """id объектов снимка в текущей сборке базы; null — объекта больше нет."""

    program_id: int | None
    olympiad: SharedOlympiad | None
    profile_id: int | None
    university: UniversityInfo | None
    diplomas: list[SharedDiploma]


class Share(ResponseModel):
    kind: ShareKind
    benefit_type: BenefitType | None
    # главный объект снимка нашёлся (направление, олимпиада); у дипломов — всегда true
    found: bool
    resolved: ShareResolved
