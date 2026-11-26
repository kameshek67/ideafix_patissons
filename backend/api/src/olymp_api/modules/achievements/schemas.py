from typing import Annotated, Literal

from pydantic import BaseModel, Field

from olymp_api.schemas import Benefit, ResponseModel, UniversityInfo


class DiplomaOlympiad(ResponseModel):
    id: int
    # ключ олимпиады в строке диплома: не меняется при пересборке базы
    key: str
    short_name: str
    canonical_name: str
    # в перечне РСОШ на 2026/27; None — перечень не применим
    in_rsosh_2026_27: bool | None


class DiplomaProfile(ResponseModel):
    id: int
    key: str
    name: str
    level: str
    # уровень по перечню РСОШ на 2026/27; пусто, если пары в перечне нет
    level_2026_27: str
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


class Changes2027(ResponseModel):
    """Что меняется по проекту правил 2027 (rules=project2027)."""

    # направления, где БВИ призёра становится «100 баллами», и вузы с такими направлениями
    to_hundred: int
    universities: int
    # направления, где БВИ может измениться, но по данным не определить — проверить в правилах
    check: int


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
    # этап ВсОШ: f — заключительный, r — региональный (льгот не даёт)
    stage: Literal["f", "r"]
    # год олимпиады вне срока действия дипломов при поступлении в admission_year
    expired: bool
    counts: Counts


class Rejected(ResponseModel):
    """Строки олимпиад дипломов, которые не подошли по условиям вуза (без учёта профиля)."""

    role: int
    grade: int
    year: int
    team: int


EgeStatus = Literal["confirmed", "short", "missing_score", "no_threshold"]
# коды предметов — olymp_domain.ege.SUBJECTS
EgeSubject = Literal[
    "rus", "math", "inf", "phys", "chem", "bio", "soc", "hist", "lit", "foreign", "geo"
]


class NoTableUniversity(ResponseModel):
    """Вуз, для которого в базе нет таблицы льгот: льготы там могут быть, но мы их не видим."""

    id: int
    name: str
    short_name: str


class EgeSummary(ResponseModel):
    """Подтверждение баллами ЕГЭ (только если баллы переданы, F-03)."""

    # направления и вузы, где хотя бы одна льгота подтверждена баллами
    confirmed_programs: int
    confirmed_universities: int
    # вузы без подтверждённых направлений, где до порога не хватает не больше 5 баллов
    close_universities: int
    # строки льгот по статусам
    statuses: dict[EgeStatus, int]


class AchievementUniversity(ResponseModel):
    university: UniversityInfo
    programs: int
    bvi: int
    sto: int
    other: int
    # направления, где профиль в правилах вуза не указан — соответствие нужно проверить
    check: int
    # направления, где по проекту правил 2027 БВИ становится «100 баллами» (иначе 0)
    to_hundred: int = 0
    # направления, подтверждённые баллами ЕГЭ (только если баллы переданы)
    ege_confirmed: int | None = None
    # строк вуза нет, но по закону диплом даёт БВИ на направления, соответствующие профилю:
    # олимпиады, по которым права нужно сверить с правилами вуза (пусто — вуз с таблицей)
    law: list[str] = []


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
    # по проекту правил 2027: hundred — БВИ станет «100 баллов», check — проверить в правилах
    change: Literal["hundred", "check"] | None = None
    # exact — профиль совпал, subject — совпал предмет, check — профиль в правилах не указан
    fit: str
    # с баллами ЕГЭ: подтверждена ли льгота, сколько не хватает, по каким предметам
    ege_status: EgeStatus | None = None
    ege_gap: int | None = None
    ege_subjects: list[str] = []


class AchievementsMatch(ResponseModel):
    """Где дипломы дают льготы: итоги, список вузов, а с university_id — строки вуза."""

    diplomas: list[DiplomaResult]
    # итоги и списки посчитаны по этим правилам: current — действующие, project2027 — проект
    rules: Literal["current", "project2027"] = "current"
    changes: Changes2027 | None = None
    totals: Counts
    rejected: Rejected
    results: list[AchievementUniversity]
    university: UniversityInfo | None = None
    rows: list[AchievementRow] = []
    ege: EgeSummary | None = None
    # вузы без таблицы льгот: подбор по ним не делался
    no_table: list[NoTableUniversity] = []
    # год данных (приёмная кампания правил) и год поступления, по которому считаются сроки
    campaign_year: int
    admission_year: int
    valid_years: list[int]


class MaxConfig(ResponseModel):
    """Что сайту нужно знать о мини-приложении MAX."""

    # API проверяет вход через MAX — дипломы можно хранить в профиле пользователя
    enabled: bool
    # публичное имя бота для ссылок https://max.ru/<имя>?startapp=...
    bot_name: str | None
    campaign_year: int
    admission_year: int
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
    # баллы ЕГЭ: предмет → балл; is_mock — пробные (ожидаемые) баллы
    ege: dict[str, int] = {}
    ege_is_mock: bool = False


class MyDiplomasUpdate(BaseModel):
    diplomas: list[str] = Field(
        max_length=20,
        description="Строки дипломов, например «высшаяпроба.математика.w.11.2025»",
    )
    # None — баллы не трогать (старые клиенты), {} — удалить
    ege: dict[EgeSubject, Annotated[int, Field(ge=0, le=100)]] | None = None
    ege_is_mock: bool = False
