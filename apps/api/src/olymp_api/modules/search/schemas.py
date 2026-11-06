from olymp_api.schemas import (
    Benefit,
    OlympiadHit,
    ProfileHit,
    ResponseModel,
    UniversityInfo,
)


class ProgramInfo(ResponseModel):
    id: int
    faculty_or_direction: str
    profile_name: str
    code: str
    note: str
    source_title: str
    source_url: str
    source_sheet: str


class BenefitGroup(ResponseModel):
    type: str
    rows: list[Benefit]
    count: int


class Note(ResponseModel):
    kind: str
    text: str


class ProgramOlympiad(ResponseModel):
    id: int
    short_name: str
    canonical_name: str | None = None
    kind: str | None = None
    types: list[str]
    count: int


class Source(ResponseModel):
    title: str
    url: str
    # page — стабильная страница раздела вуза, file — конкретный документ
    kind: str
    types: list[str]
    checked_at: str | None = None


class ProgramSearch(ResponseModel):
    """«Ищу олимпиады под вуз»: таблицы льгот направления, примечания и источники."""

    program: ProgramInfo
    university: UniversityInfo
    groups: list[BenefitGroup]
    notes: list[Note]
    olympiads: list[ProgramOlympiad]
    sources: list[Source]
    total_benefits: int


class ProgramRef(ResponseModel):
    id: int
    faculty_or_direction: str
    profile_name: str
    code: str
    note: str
    source_url: str
    source_title: str


class ProgramResult(ResponseModel):
    program: ProgramRef
    benefits: list[Benefit]
    types: list[str]


class UniversityResult(ResponseModel):
    university: UniversityInfo
    programs: list[ProgramResult]
    programs_total: int
    bvi: int
    sto: int
    other: int


class FallbackHit(ResponseModel):
    id: int
    benefit_type: str
    text: str
    program_id: int
    faculty_or_direction: str
    university: str


class OlympiadSearch(ResponseModel):
    """«Куда поступить с моей олимпиадой»: список вузов, а с university_id — строки вуза."""

    query: str
    matched_olympiads: list[OlympiadHit]
    profiles: list[ProfileHit]
    profile_id: int | None = None
    without_profile: int = 0
    results: list[UniversityResult]
    total_programs: int
    shown_programs: int = 0
    total_universities: int
    truncated: bool = False
    # олимпиада не опознана — похожие строки по тексту условий
    fallback: list[FallbackHit] = []
