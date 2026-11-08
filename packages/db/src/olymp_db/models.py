"""Модели БД «Олимпа» (PostgreSQL).

Нормализованная часть: universities / programs / benefits.
Поисковая часть: olympiads / olympiad_aliases / olympiad_profiles / benefit_olympiads /
benefit_keywords / search_index (полнотекстовый индекс, tsvector).
Пользовательская часть: max_users / user_diplomas («Мои дипломы» в мини-приложении MAX),
share_links (снимки для ссылок «Поделиться»).

Все текстовые колонки — с сортировкой «C»: строки упорядочиваются побайтно, как в
прототипе на SQLite. От этого зависит порядок вузов, направлений и профилей в выдаче.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

BENEFIT_TYPES = ("БВИ", "100 баллов", "Особое право (БВИ/100)", "Фаст-трек", "ИД (доп. баллы)")
LAYERS = ("summary", "detailed", "derived", "raw")

CText = Text(collation="C")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _pk() -> Mapped[int]:
    return mapped_column(Integer, primary_key=True)


def _text(default: str = "") -> Mapped[str]:
    return mapped_column(CText, default=default, server_default=sa_text(f"'{default}'"))


def _int(default: int = 0) -> Mapped[int]:
    return mapped_column(Integer, default=default, server_default=sa_text(str(default)))


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class University(Base):
    __tablename__ = "universities"

    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(CText, unique=True)
    short_name: Mapped[str] = mapped_column(CText)
    region: Mapped[str] = _text()
    # город/площадка для показа в таблицах («Приволжский ФО» -> «Казань»)
    city: Mapped[str] = _text()
    note: Mapped[str] = _text()
    # запасная ссылка на документ вуза: берётся из самого частого источника
    site_url: Mapped[str] = _text()
    # стабильная страница раздела «Документы / Олимпиады» (university_pages.py).
    # Именно она показывается пользователю: прямые файлы меняются каждый сезон.
    docs_url: Mapped[str] = _text()
    docs_title: Mapped[str] = _text()
    # укрупнённый фильтр для фронта: Москва / Санкт-Петербург / Регионы
    region_group: Mapped[str] = _text("Регионы")


class Program(Base):
    __tablename__ = "programs"
    __table_args__ = (Index(None, "university_id"), Index(None, "code"))

    id: Mapped[int] = _pk()
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id", ondelete="CASCADE"))
    faculty_or_direction: Mapped[str] = mapped_column(CText)
    profile_name: Mapped[str] = _text()
    code: Mapped[str] = _text()
    note: Mapped[str] = _text()
    # название документа приёмной комиссии и отдельно ссылка на него
    source_title: Mapped[str] = _text()
    source_url: Mapped[str] = _text()
    source_sheet: Mapped[str] = _text()
    sort_order: Mapped[int] = _int()


class Benefit(Base):
    """Льгота направления.

    layer: detailed — строка таблицы «олимпиада × профиль» (из подробного листа или
    разобранная из перечисления в «Базе»); summary — текстовое правило без названий
    олимпиад (идёт в примечания); derived — строка, выведенная из правила «любая
    олимпиада перечня по профилю X»; raw — исходное перечисление, уже разложенное в
    строки таблицы (хранится для трассировки, в выдачу не попадает).
    """

    __tablename__ = "benefits"
    __table_args__ = (
        CheckConstraint(f"benefit_type IN ({_in(BENEFIT_TYPES)})", name="benefit_type"),
        CheckConstraint(f"layer IN ({_in(LAYERS)})", name="layer"),
        Index(None, "program_id"),
        Index(None, "benefit_type"),
        Index(None, "layer"),
    )

    id: Mapped[int] = _pk()
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"))
    benefit_type: Mapped[str] = mapped_column(CText)
    raw_conditions_text: Mapped[str] = mapped_column(CText)
    layer: Mapped[str] = _text("summary")
    olympiad_profile: Mapped[str] = _text()
    olympiad_subject: Mapped[str] = _text()
    level: Mapped[str] = _text()
    winner_role: Mapped[str] = _text()
    grade: Mapped[str] = _text()
    confirm_subject: Mapped[str] = _text()
    min_ege: Mapped[str] = _text()
    # разобранные confirm_subject и min_ege (olymp_domain.ege): коды предметов — NULL, если текст
    # не разобран, пустой список — предмет не указан (по профилю олимпиады); порог — NULL, если нет
    confirm_subjects: Mapped[list[str] | None] = mapped_column(ARRAY(CText), nullable=True)
    min_ege_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    award_subject: Mapped[str] = _text()
    years: Mapped[str] = _text()
    note: Mapped[str] = _text()
    source_title: Mapped[str] = _text()
    source_url: Mapped[str] = _text()
    source_sheet: Mapped[str] = _text()


class Olympiad(Base):
    __tablename__ = "olympiads"
    __table_args__ = (Index("ix_olympiads_mentions", sa_text("mentions DESC")),)

    id: Mapped[int] = _pk()
    canonical_name: Mapped[str] = mapped_column(CText, unique=True)
    short_name: Mapped[str] = mapped_column(CText)
    # по ключу олимпиаду ищут дипломы и ссылки «Поделиться»: два одинаковых — ошибка сборки
    squash_key: Mapped[str] = mapped_column(CText, unique=True)
    kind: Mapped[str] = _text("rsosh")
    is_featured: Mapped[int] = _int()
    mentions: Mapped[int] = _int()
    bvi_count: Mapped[int] = _int()
    sto_count: Mapped[int] = _int()
    uni_count: Mapped[int] = _int()


class OlympiadAlias(Base):
    __tablename__ = "olympiad_aliases"
    __table_args__ = (UniqueConstraint("olympiad_id", "squash_alias"), Index(None, "squash_alias"))

    id: Mapped[int] = _pk()
    olympiad_id: Mapped[int] = mapped_column(ForeignKey("olympiads.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(CText)
    squash_alias: Mapped[str] = mapped_column(CText)
    is_generic: Mapped[int] = _int()


class OlympiadProfile(Base):
    """Профиль олимпиады: у НТО их несколько десятков, и льгота даётся
    за пару «олимпиада + профиль», а не за олимпиаду целиком."""

    __tablename__ = "olympiad_profiles"
    __table_args__ = (UniqueConstraint("olympiad_id", "squash_key"), Index(None, "olympiad_id"))

    id: Mapped[int] = _pk()
    olympiad_id: Mapped[int] = mapped_column(ForeignKey("olympiads.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(CText)
    squash_key: Mapped[str] = mapped_column(CText)
    # преобладающий уровень пары «олимпиада + профиль»
    level: Mapped[str] = _text()
    mentions: Mapped[int] = _int()
    bvi_count: Mapped[int] = _int()
    sto_count: Mapped[int] = _int()
    uni_count: Mapped[int] = _int()


class OlympiadInfo(Base):
    """Карточка олимпиады из data/olympiad_cards.json: что внутри и где официальный сайт."""

    __tablename__ = "olympiad_info"

    id: Mapped[int] = _pk()
    olympiad_id: Mapped[int] = mapped_column(
        ForeignKey("olympiads.id", ondelete="CASCADE"), unique=True
    )
    site_url: Mapped[str] = _text()
    summary: Mapped[str] = _text()
    grades: Mapped[str] = _text()
    formats: Mapped[list[str]] = mapped_column(ARRAY(CText), server_default=sa_text("'{}'"))
    stages: Mapped[list[str]] = mapped_column(ARRAY(CText), server_default=sa_text("'{}'"))
    source_url: Mapped[str] = _text()
    checked: Mapped[date] = mapped_column(Date)


class OlympiadTrack(Base):
    """Секция или трек олимпиады. Льготы у трека те же, что у его профиля РСОШ."""

    __tablename__ = "olympiad_tracks"
    __table_args__ = (UniqueConstraint("olympiad_id", "squash_key"), Index(None, "profile_id"))

    id: Mapped[int] = _pk()
    olympiad_id: Mapped[int] = mapped_column(ForeignKey("olympiads.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(ForeignKey("olympiad_profiles.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(CText)
    squash_key: Mapped[str] = mapped_column(CText)
    topics: Mapped[list[str]] = mapped_column(ARRAY(CText), server_default=sa_text("'{}'"))
    source_url: Mapped[str] = _text()
    checked: Mapped[date] = mapped_column(Date)


class BenefitOlympiad(Base):
    """Связка «льгота ↔ олимпиада (+профиль)»: ядро обратного поиска."""

    __tablename__ = "benefit_olympiads"
    __table_args__ = (
        UniqueConstraint("benefit_id", "olympiad_id", "profile", "level"),
        Index(None, "olympiad_id"),
        Index(None, "benefit_id"),
        Index(None, "profile_id"),
    )

    id: Mapped[int] = _pk()
    benefit_id: Mapped[int] = mapped_column(ForeignKey("benefits.id", ondelete="CASCADE"))
    olympiad_id: Mapped[int] = mapped_column(ForeignKey("olympiads.id", ondelete="CASCADE"))
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("olympiad_profiles.id", ondelete="SET NULL")
    )
    profile: Mapped[str] = _text()
    level: Mapped[str] = _text()
    winner_role: Mapped[str] = _text()
    matched_via: Mapped[str] = _text("column")  # column | text


class BenefitKeyword(Base):
    """Ключевые слова, вытащенные алгоритмически из текста условий."""

    __tablename__ = "benefit_keywords"
    __table_args__ = (
        UniqueConstraint("benefit_id", "kind", "keyword"),
        Index(None, "keyword"),
        Index(None, "kind"),
    )

    id: Mapped[int] = _pk()
    benefit_id: Mapped[int] = mapped_column(ForeignKey("benefits.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(CText)  # level | role | grade | ege | subject
    keyword: Mapped[str] = mapped_column(CText)


class UniversityDocument(Base):
    """Файлы, найденные на странице вуза обходчиком refresh_sources."""

    __tablename__ = "university_documents"
    __table_args__ = (UniqueConstraint("university_id", "url"), Index(None, "university_id"))

    id: Mapped[int] = _pk()
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(CText)
    url: Mapped[str] = mapped_column(CText)
    checked_at: Mapped[str] = _text()


class SearchIndex(Base):
    """Полнотекстовый индекс по условиям льгот: одна запись на льготу."""

    __tablename__ = "search_index"
    __table_args__ = (Index(None, "document", postgresql_using="gin"),)

    benefit_id: Mapped[int] = mapped_column(
        ForeignKey("benefits.id", ondelete="CASCADE"), primary_key=True
    )
    document: Mapped[str] = mapped_column(TSVECTOR)


class IngestLog(Base):
    __tablename__ = "ingest_log"

    id: Mapped[int] = _pk()
    sheet: Mapped[str] = mapped_column(CText)
    rows_read: Mapped[int] = _int()
    rows_ingested: Mapped[int] = _int()
    benefits: Mapped[int] = _int()
    comment: Mapped[str] = _text()


class Meta(Base):
    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(CText, primary_key=True)
    value: Mapped[str] = mapped_column(CText)


# ---------------------------------------------------------------- индивидуальные достижения
# Баллы вузов за ИД (ГТО, аттестат с отличием, спорт…): data/individual_achievements*.csv,
# наполняет olymp-ingest в той же транзакции. У каждой строки есть документ-источник.

ACHIEVEMENT_REVIEW = ("extracted", "reviewed")


class IndividualAchievement(Base):
    """Сколько баллов вуз начисляет за одно достижение (правило, а не диплом школьника)."""

    __tablename__ = "individual_achievements"
    __table_args__ = (
        CheckConstraint(f"review IN ({_in(ACHIEVEMENT_REVIEW)})", name="review"),
        CheckConstraint("points >= 0", name="points"),
        Index(None, "university_id", "admission_year"),
    )

    id: Mapped[int] = _pk()
    rule_key: Mapped[str] = mapped_column(CText, unique=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id", ondelete="CASCADE"))
    admission_year: Mapped[int] = mapped_column(SmallInteger)
    kind: Mapped[str] = mapped_column(CText)
    # вид внутри типа (gold/silver/bronze, kms…); пусто — подходит любой
    variants: Mapped[list[str]] = mapped_column(ARRAY(CText), server_default=sa_text("'{}'"))
    points: Mapped[int] = mapped_column(SmallInteger)
    # годы получения, которые засчитываются; пусто — без ограничения
    years: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), server_default=sa_text("'{}'"))
    # не старше N лет к году приёма (ГТО: «текущий и предшествующий год» — 1)
    recency_years: Mapped[int | None] = mapped_column(SmallInteger)
    # внутри группы засчитывается только лучшее («за один вид достижений»)
    exclusive_group: Mapped[str] = _text()
    label: Mapped[str] = _text()
    notes: Mapped[str] = _text()
    source_url: Mapped[str] = _text()
    source_page: Mapped[int | None] = mapped_column(SmallInteger)
    source_quote: Mapped[str] = _text()
    # extracted — разобрано из документа вуза, человек не сверял; reviewed — сверено
    review: Mapped[str] = _text("extracted")


class IndividualAchievementLimit(Base):
    """Потолок суммы баллов за ИД у вуза. Нет строки — в документе вуза потолок не найден."""

    __tablename__ = "individual_achievement_limits"
    __table_args__ = (
        UniqueConstraint("university_id", "admission_year"),
        CheckConstraint("max_total >= 0", name="max_total"),
    )

    id: Mapped[int] = _pk()
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id", ondelete="CASCADE"))
    admission_year: Mapped[int] = mapped_column(SmallInteger)
    max_total: Mapped[int] = mapped_column(SmallInteger)
    source_url: Mapped[str] = _text()
    source_page: Mapped[int | None] = mapped_column(SmallInteger)
    source_quote: Mapped[str] = _text()
    review: Mapped[str] = _text("extracted")


# ---------------------------------------------------------------- пользователи MAX
# Данные пользователей не входят в DATA_TABLES: пересборка базы их не трогает. Поэтому
# дипломы ссылаются на олимпиады и профили ключами squash, а не id — id после пересборки
# другие, а ключи (squash названий) прежние.


class MaxUser(Base):
    """Пользователь мини-приложения MAX — из подписанных данных запуска (initData)."""

    __tablename__ = "max_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    first_name: Mapped[str] = _text()
    last_name: Mapped[str] = _text()
    username: Mapped[str] = _text()
    language_code: Mapped[str] = _text()
    photo_url: Mapped[str] = _text()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserDiploma(Base):
    """Диплом олимпиады в профиле ученика («Мои дипломы»)."""

    __tablename__ = "user_diplomas"
    __table_args__ = (
        UniqueConstraint("user_id", "position"),
        CheckConstraint("role IN ('w', 'p')", name="role"),
        CheckConstraint("grade IS NULL OR grade BETWEEN 9 AND 11", name="grade"),
        CheckConstraint("year IS NULL OR year BETWEEN 2000 AND 2100", name="year"),
    )

    id: Mapped[int] = _pk()
    # поиск по user_id обслуживает уникальный индекс (user_id, position)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("max_users.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    olympiad_key: Mapped[str] = mapped_column(CText)
    profile_key: Mapped[str | None] = mapped_column(CText, nullable=True)
    role: Mapped[str] = mapped_column(CText)
    grade: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    year: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # названия на момент сохранения — показать диплом, даже если олимпиада ушла из базы
    olympiad_name: Mapped[str] = _text()
    profile_name: Mapped[str] = _text()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserEgeScore(Base):
    """Баллы ЕГЭ ученика (F-03): только в его профиле MAX, без истории и логов."""

    __tablename__ = "user_ege_scores"
    __table_args__ = (CheckConstraint("score BETWEEN 0 AND 100", name="score"),)

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("max_users.id", ondelete="CASCADE"), primary_key=True
    )
    subject: Mapped[str] = mapped_column(CText, primary_key=True)
    score: Mapped[int] = mapped_column(SmallInteger)
    # пробные (ожидаемые) баллы, а не результат экзамена
    is_mock: Mapped[bool] = mapped_column(Boolean, server_default=sa_text("false"))


class ShareLink(Base):
    """Снимок для ссылки «Поделиться»: что открыть получателю (F-01).

    Хранит стабильные ключи (squash названий), а не id: ссылка открывает тот же экран и
    после пересборки базы. Внешних ключей на таблицы сборки нет и быть не должно — иначе
    пересборка (она удаляет строки таблиц сборки) упёрлась бы во внешний ключ.
    """

    __tablename__ = "share_links"
    __table_args__ = (
        CheckConstraint("kind IN ('program', 'olympiad', 'diplomas')", name="kind"),
        Index(None, "expires_at"),
    )

    # 10 символов base62 из secrets — непредсказуем, годится и для startapp, и для пути /s/
    token: Mapped[str] = mapped_column(CText, primary_key=True)
    kind: Mapped[str] = mapped_column(CText)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # sha256 канонического JSON (kind + payload): повторное «Поделиться» отдаёт тот же токен
    payload_hash: Mapped[str] = mapped_column(CText, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # ссылка живёт 90 дней с последнего «Поделиться» этого же экрана
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    opened_count: Mapped[int] = _int()
    last_opened: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DataReport(Base):
    """Сообщение «Нашли ошибку в данных» (T-079). Не таблица сборки: переживает пересборку,
    поэтому хранит названия на момент сообщения, а id — только для справки (без внешних ключей)."""

    __tablename__ = "data_reports"
    __table_args__ = (
        CheckConstraint("kind IN ('program', 'olympiad')", name="kind"),
        Index(None, "created_at"),
    )

    id: Mapped[int] = _pk()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    kind: Mapped[str] = mapped_column(CText)
    program_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    olympiad_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    university_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # что было на экране: вуз, направление, олимпиада — названия из базы, не от клиента
    context: Mapped[dict[str, Any]] = mapped_column(JSONB)
    message: Mapped[str] = mapped_column(CText)
    status: Mapped[str] = _text("new")


# Таблицы с данными сборки: их очищает и заново наполняет olymp-ingest.
DATA_TABLES = [
    "olympiad_tracks",
    "olympiad_info",
    "search_index",
    "benefit_keywords",
    "benefit_olympiads",
    "olympiad_profiles",
    "olympiad_aliases",
    "olympiads",
    "benefits",
    "individual_achievements",
    "individual_achievement_limits",
    "programs",
    "university_documents",
    "universities",
    "ingest_log",
    "meta",
]
