"""Схемы ответов, общие для модулей (контракт API).

Поля повторяют ответы прототипа: фронтенд переносился без изменения логики.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ResponseModel(BaseModel):
    """Поля со значениями по умолчанию в контракте считаются обязательными (их всегда отдаём)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class OlympiadHit(ResponseModel):
    """Олимпиада в автокомплите и в выдаче поиска."""

    id: int
    canonical_name: str
    short_name: str
    kind: str
    mentions: int
    bvi_count: int
    sto_count: int
    uni_count: int
    # в перечне РСОШ на 2026/27; None — перечень не применим (ВсОШ, настоящие международные)
    in_rsosh_2026_27: bool | None = None
    # насколько точно совпал запрос (0 — точное совпадение сокращения); только при поиске по q
    rank: int | None = None
    is_featured: int | None = None
    # число профилей олимпиады; только в /v1/olympiads
    profiles: int | None = None
    # запрос «нто ии» опознан как олимпиада + профиль; только в /v1/olympiads?with_profile=true
    profile_id: int | None = None
    profile_name: str | None = None


class ProfileHit(ResponseModel):
    id: int
    olympiad_id: int | None = None
    name: str
    mentions: int
    bvi_count: int
    sto_count: int
    uni_count: int
    # уровень по документам вузов и по перечню РСОШ на 2026/27 (пусто, если пары в перечне нет)
    level: str = ""
    level_2026_27: str = ""


class OlympiadRef(ResponseModel):
    """Олимпиада, к которой привязана строка льготы."""

    id: int
    short_name: str
    canonical_name: str | None = None
    kind: str | None = None


class Matched(ResponseModel):
    """Через какую пару «олимпиада + профиль» строка попала в обратный поиск."""

    profile: str
    profile_id: int | None
    level: str
    role: str
    via: str


class Benefit(ResponseModel):
    id: int
    benefit_type: str
    layer: str
    # строка выведена из правила «любая олимпиада перечня по профилю X»
    derived: bool
    text: str
    olympiad_profile: str
    olympiad_subject: str
    level: str
    winner_role: str
    grade: str
    confirm_subject: str
    min_ege: str
    award_subject: str
    years: str
    note: str
    source_title: str
    source_url: str
    source_sheet: str
    # у строк слоя document: страница документа вуза (у xlsx — лист) и цитата из него
    source_page: int | None = None
    source_quote: str = ""
    # стабильный ключ строки: по нему приходит жалоба «не совпадает с документом»
    row_key: str = ""
    # когда по жалобе пользователя строку исправили; None — не исправляли
    fixed_at: datetime | None = None
    olympiads: list[OlympiadRef]
    matched: Matched | None = None


class UniversityInfo(ResponseModel):
    id: int
    name: str
    short_name: str
    region: str
    city: str
    note: str
    site_url: str = ""
    docs_url: str = ""
    docs_title: str = ""
    region_group: str
