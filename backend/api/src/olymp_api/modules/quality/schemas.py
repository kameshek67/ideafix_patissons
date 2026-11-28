from olymp_api.schemas import ResponseModel


class ExtractionScore(ResponseModel):
    """Один способ получить таблицу льгот, сверенный с ручной разметкой документов."""

    documents: int
    records: int  # строк в разметке
    precision: float  # доля найденных строк, которые есть в разметке
    recall: float  # доля строк разметки, которые найдены
    who: float | None  # верно ли указано, кому льгота (победителям или и призёрам)


class ExtractionSet(ResponseModel):
    old_table: ExtractionScore | None  # прежняя таблица из XLSX
    extraction: ExtractionScore | None  # извлечение из самих документов вузов


class ExtractionQuality(ResponseModel):
    development: ExtractionSet  # эталон, на котором настраивали извлечение
    holdout: ExtractionSet  # отложенные страницы, на них извлечение не настраивали


class WithoutTable(ResponseModel):
    id: int
    name: str


class Coverage(ResponseModel):
    universities: int
    with_table: int
    without_table: list[WithoutTable]
    layers: dict[str, int]  # слой -> число строк льгот (без исходного перечисления)


class Freshness(ResponseModel):
    built_at: str | None
    rsosh_list: str | None  # когда загружен перечень РСОШ 2026/27
    documents_checked_from: str | None  # самая давняя проверка ссылок на документы вузов
    documents_checked_to: str | None  # самая свежая


class ReportsPeriod(ResponseModel):
    received: int
    fixed: int  # ошибка подтвердилась и исправлена
    correct: int  # данные оказались верными
    median_hours: float | None  # медиана от жалобы до решения


class ReportsQuality(ResponseModel):
    total: ReportsPeriod
    days_30: ReportsPeriod


class AssistantModel(ResponseModel):
    model: str
    cases: int | None
    passed_share: float | None
    error_share_raw: float | None  # ошибок факта до проверки кодом
    error_share_final: float | None  # и после неё
    answer_p95: float | None  # секунд до полного ответа, 95-й перцентиль
    cost_per_answer: float | None  # долларов
    gate_passed: bool | None  # прошла порог включения


class AssistantQuality(ResponseModel):
    model: str
    date: str | None
    cases: int | None
    passed_share: float | None
    error_share: float | None  # ответов с ошибкой факта после проверки
    fabrication: float | None  # выдумок там, где данных нет
    answer_p50: float | None  # секунд до полного ответа, медиана
    cost_per_answer: float | None
    models: list[AssistantModel]  # все прогоны сравнения моделей


class Quality(ResponseModel):
    extraction: ExtractionQuality
    coverage: Coverage
    freshness: Freshness
    reports: ReportsQuality
    assistant: AssistantQuality | None
