from olymp_api.schemas import OlympiadHit, ProfileHit, ResponseModel


class StatsTotals(ResponseModel):
    universities: int
    programs: int
    benefits: int
    bvi: int
    sto: int
    olympiads: int
    profiles: int
    links: int
    keywords: int
    rows: int
    derived: int
    notes: int


class StatsUniversity(ResponseModel):
    id: int
    name: str
    short_name: str
    region: str
    city: str
    region_group: str
    programs: int
    bvi: int
    sto: int
    benefits: int


class StatsOlympiad(ResponseModel):
    id: int
    short_name: str
    canonical_name: str
    mentions: int
    bvi_count: int
    sto_count: int
    uni_count: int


class SheetLog(ResponseModel):
    sheet: str
    rows_read: int
    rows_ingested: int
    benefits: int
    comment: str


class Stats(ResponseModel):
    totals: StatsTotals
    source_file: str
    built_at: str
    benefit_types: dict[str, int]
    universities: list[StatsUniversity]
    top_olympiads: list[StatsOlympiad]
    sheets: list[SheetLog]


class RegionGroup(ResponseModel):
    name: str
    universities: int
    regions: list[str]


class Regions(ResponseModel):
    items: list[RegionGroup]


class UniversityItem(ResponseModel):
    id: int
    name: str
    short_name: str
    region: str
    city: str
    note: str
    region_group: str
    programs: int
    bvi: int
    sto: int
    benefits: int


class Universities(ResponseModel):
    count: int
    items: list[UniversityItem]
    regions: list[str]


class ProgramItem(ResponseModel):
    id: int
    university_id: int
    faculty_or_direction: str
    profile_name: str
    code: str
    note: str
    source_url: str
    source_sheet: str
    university: str
    university_short: str
    region: str
    region_group: str
    bvi: int
    sto: int
    benefits: int


class Programs(ResponseModel):
    count: int
    items: list[ProgramItem]


class Olympiads(ResponseModel):
    count: int
    items: list[OlympiadHit]


class OlympiadProfiles(ResponseModel):
    olympiad: OlympiadHit
    count: int
    items: list[ProfileHit]
    # связей олимпиады без профиля: правила сформулированы общим текстом
    without_profile: int
