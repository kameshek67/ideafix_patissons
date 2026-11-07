from pydantic import BaseModel, Field

from olymp_api.schemas import Benefit, ResponseModel, UniversityInfo


class DiplomaOlympiad(ResponseModel):
    id: int
    # ключ олимпиады в строке диплома: не меняется при пересборке базы
    key: str
    short_name: str
    canonical_name: str


class DiplomaProfile(ResponseModel):
    id: int
    key: str
    name: str
    level: str
    mentions: int


class DiplomaForm(ResponseModel):
    """Олимпиада для формы диплома: ключ и профили, которые можно выбрать."""

    olympiad: DiplomaOlympiad
    profiles: list[DiplomaProfile]


class Counts(ResponseModel):
    """Сколько направлений дают льготу; каждое считается по лучшей льготе."""

    universities: int
    programs: int
    bvi: int
    sto: int
    other: int


class DiplomaResult(ResponseModel):
    # нормализованная строка диплома (см. olymp_domain.diplomas)
    spec: str
    # олимпиада и профиль нашлись в текущей базе
    found: bool
    olympiad: DiplomaOlympiad | None
    profile: DiplomaProfile | None
    role: str
    grade: int | None
    year: int | None
    # год олимпиады вне срока действия дипломов в эту приёмную кампанию
    expired: bool
    counts: Counts


class Rejected(ResponseModel):
    """Строки олимпиад дипломов, которые не подошли по условиям вуза (без учёта профиля)."""

    role: int
    grade: int
    year: int
    team: int


class AchievementUniversity(ResponseModel):
    university: UniversityInfo
    programs: int
    bvi: int
    sto: int
    other: int
    # направления, где профиль в правилах вуза не указан — соответствие нужно проверить
    check: int


class AchievementProgram(ResponseModel):
    id: int
    faculty_or_direction: str
    profile_name: str
    code: str


class AchievementRow(ResponseModel):
    program: AchievementProgram
    benefit: Benefit
    # номера дипломов (в порядке запроса), которые дают эту льготу
    diplomas: list[int]
    # exact — профиль совпал, subject — совпал предмет, check — профиль в правилах не указан
    fit: str


class AchievementsMatch(ResponseModel):
    """Где дипломы дают льготы: итоги, список вузов, а с university_id — строки вуза."""

    diplomas: list[DiplomaResult]
    totals: Counts
    rejected: Rejected
    results: list[AchievementUniversity]
    university: UniversityInfo | None = None
    rows: list[AchievementRow] = []
    campaign_year: int
    valid_years: list[int]


class MaxConfig(ResponseModel):
    """Что сайту нужно знать о мини-приложении MAX."""

    # API проверяет вход через MAX — дипломы можно хранить в профиле пользователя
    enabled: bool
    # публичное имя бота для ссылок https://max.ru/<имя>?startapp=...
    bot_name: str | None
    campaign_year: int
    valid_years: list[int]


class MaxProfile(ResponseModel):
    id: int
    first_name: str
    last_name: str
    username: str
    photo_url: str


class SavedDiploma(ResponseModel):
    spec: str
    # названия на момент сохранения: показать диплом, если олимпиады уже нет в базе
    olympiad_name: str
    profile_name: str


class MyDiplomas(ResponseModel):
    user: MaxProfile
    diplomas: list[SavedDiploma]


class MyDiplomasUpdate(BaseModel):
    diplomas: list[str] = Field(
        max_length=20,
        description="Строки дипломов, например «высшаяпроба.математика.w.11.2025»",
    )
