from typing import Literal

from pydantic import BaseModel, Field

from olymp_api.schemas import ResponseModel

Kind = Literal[
    "honors_document",
    "gto_badge",
    "olympiad_final",
    "olympiad_regional",
    "olympiad_other",
    "sport_title",
    "volunteer",
    "military",
    "abilimpics",
    "essay",
    "other",
]
Review = Literal["extracted", "reviewed"]


class Source(ResponseModel):
    url: str
    page: int | None
    quote: str


class ExtraRule(ResponseModel):
    id: str
    kind: Kind
    label: str
    points: int
    variants: list[str]
    years: list[int]
    recency_years: int | None
    exclusive_group: str | None
    notes: str
    review: Review
    source: Source


class ExtraUniversity(ResponseModel):
    id: int
    name: str
    short_name: str
    rules: int


class ExtraUniversities(ResponseModel):
    admission_year: int
    items: list[ExtraUniversity]


class ExtraRules(ResponseModel):
    university_id: int
    admission_year: int
    # лимит суммы баллов за ИД; None — в документе вуза он не найден
    max_total: int | None
    max_total_source: Source | None
    rules: list[ExtraRule]


class ClaimIn(BaseModel):
    kind: Kind
    variant: str | None = Field(None, max_length=40, description="gold/silver/bronze, kms…")
    year: int | None = Field(None, ge=2000, le=2100, description="год получения")
    rule_id: str | None = Field(None, max_length=120, description="правило, выбранное на экране")


class ScoreRequest(BaseModel):
    """Достижения школьника. Ничего не сохраняется и не пишется в журнал."""

    university_id: int
    admission_year: int = Field(ge=2000, le=2100)
    claims: list[ClaimIn] = Field(max_length=40)


class Award(ResponseModel):
    rule_id: str
    kind: Kind
    label: str
    points: int
    review: Review
    source: Source


class Skipped(ResponseModel):
    rule_id: str
    kind: Kind
    label: str
    reason: Literal[
        "year_missing", "year_not_allowed", "too_old", "year_in_future", "same_group_better"
    ]


class Unmatched(ResponseModel):
    kind: Kind
    variant: str | None
    year: int | None
    rule_id: str | None


class Score(ResponseModel):
    university_id: int
    admission_year: int
    status: Literal["scored", "no_data"]  # no_data — правил ИД этого вуза в базе нет
    total: int
    raw_total: int
    capped: bool
    max_total: int | None
    awards: list[Award]
    skipped: list[Skipped]
    unmatched: list[Unmatched]
    # хотя бы одно из учтённых правил ещё не сверено человеком
    unverified: bool
