"""Баллы за индивидуальные достижения (ИД): ГТО, аттестат с отличием, спорт и т. п.

Вуз прибавляет баллы за ИД к конкурсным; общая сумма ограничена (по порядку приёма для
бакалавриата и специалитета — не больше 10). Чистая логика без базы: правила и лимит
приходят снаружи, ответ — сколько баллов, за что и что не засчитано.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .textutils import squash

KINDS: tuple[str, ...] = (
    "honors_document",  # аттестат/диплом с отличием, медаль
    "gto_badge",  # знак ГТО (variants: gold, silver, bronze)
    "olympiad_final",  # заключительный этап ВсОШ
    "olympiad_regional",  # региональный этап ВсОШ
    "olympiad_other",  # другие олимпиады и конкурсы
    "sport_title",  # спортивное звание или разряд
    "volunteer",  # волонтёрство
    "military",  # военная служба
    "abilimpics",  # чемпионат «Абилимпикс»
    "essay",  # итоговое сочинение
    "other",
)

KIND_LABELS: dict[str, str] = {
    "honors_document": "Аттестат / диплом с отличием",
    "gto_badge": "Знак ГТО",
    "olympiad_final": "Заключительный этап ВсОШ",
    "olympiad_regional": "Региональный этап ВсОШ",
    "olympiad_other": "Олимпиады и конкурсы",
    "sport_title": "Спортивное звание или разряд",
    "volunteer": "Волонтёрство",
    "military": "Военная служба",
    "abilimpics": "Абилимпикс",
    "essay": "Итоговое сочинение",
    "other": "Другое",
}


class Skip(StrEnum):
    """Почему достижение, подходящее по виду, не принесло баллов."""

    YEAR_MISSING = "year_missing"  # правилу нужен год, а он не указан
    YEAR_NOT_ALLOWED = "year_not_allowed"  # вуз не засчитывает этот год
    TOO_OLD = "too_old"  # достижение старше срока давности
    YEAR_IN_FUTURE = "year_in_future"  # год позже года приёма
    SAME_GROUP_BETTER = "same_group_better"  # в группе «лучшее из» засчитано другое


@dataclass(frozen=True)
class ExtraRule:
    """Сколько баллов вуз начисляет за одно достижение."""

    rule_id: str
    kind: str
    points: int
    admission_year: int
    variants: tuple[str, ...] = ()  # пусто — подходит любой вид (gold/silver/bronze, kms…)
    years: tuple[int, ...] = ()  # годы получения, которые засчитываются
    recency_years: int | None = None  # не старше N лет к году приёма
    exclusive_group: str | None = None  # внутри группы засчитывается только лучшее
    label: str = ""
    source_url: str = ""
    source_page: int | None = None
    source_quote: str = ""
    review: str = "extracted"  # extracted | reviewed


@dataclass(frozen=True)
class Claim:
    """Достижение, которое отметил школьник."""

    kind: str
    variant: str | None = None
    year: int | None = None
    rule_id: str | None = None  # выбранное на экране правило; без него — любое того же вида


@dataclass(frozen=True)
class Award:
    rule: ExtraRule


@dataclass(frozen=True)
class Skipped:
    rule: ExtraRule
    reason: Skip


@dataclass(frozen=True)
class ExtraScore:
    total: int  # после лимита
    raw_total: int  # без лимита
    capped: bool
    max_total: int | None  # None — лимит в документе вуза не найден
    awards: tuple[Award, ...] = ()
    skipped: tuple[Skipped, ...] = ()
    unmatched: tuple[Claim, ...] = field(default=())  # у вуза нет правила для этих достижений


def _matches(rule: ExtraRule, claim: Claim) -> bool:
    if claim.rule_id is not None and claim.rule_id != rule.rule_id:
        return False
    if rule.kind != claim.kind:
        return False
    if not rule.variants:
        return True
    return claim.variant is not None and squash(claim.variant) in {squash(v) for v in rule.variants}


def _year_problem(rule: ExtraRule, claim: Claim) -> Skip | None:
    if not rule.years and rule.recency_years is None:
        return None
    if claim.year is None:
        return Skip.YEAR_MISSING
    if claim.year > rule.admission_year:
        return Skip.YEAR_IN_FUTURE
    if rule.years and claim.year not in rule.years:
        return Skip.YEAR_NOT_ALLOWED
    if rule.recency_years is not None and rule.admission_year - claim.year > rule.recency_years:
        return Skip.TOO_OLD
    return None


def score(
    rules: Sequence[ExtraRule], claims: Sequence[Claim], max_total: int | None = None
) -> ExtraScore:
    """Баллы за ИД одного вуза и года приёма.

    Каждое правило даёт баллы один раз, сколько бы подтверждений ни было. Группа
    ``exclusive_group`` даёт только лучшее правило. Сумма режется по лимиту вуза; если он
    неизвестен (``None``), сумма не режется, а ответ честно это сообщает.
    """
    awards: list[ExtraRule] = []
    skipped: dict[str, Skipped] = {}
    matched: set[int] = set()
    for rule in sorted(rules, key=lambda r: r.rule_id):
        problem: Skip | None = None
        granted = False
        for i, claim in enumerate(claims):
            if not _matches(rule, claim):
                continue
            matched.add(i)
            problem = _year_problem(rule, claim)
            if problem is None:
                granted = True
                break
        if granted:
            awards.append(rule)
        elif problem is not None:
            skipped[rule.rule_id] = Skipped(rule, problem)

    best: dict[str, ExtraRule] = {}
    for rule in awards:
        group = rule.exclusive_group
        if group is not None and (group not in best or rule.points > best[group].points):
            best[group] = rule
    final: list[ExtraRule] = []
    for rule in awards:
        if rule.exclusive_group is not None and best[rule.exclusive_group] is not rule:
            skipped[rule.rule_id] = Skipped(rule, Skip.SAME_GROUP_BETTER)
        else:
            final.append(rule)

    raw = sum(r.points for r in final)
    total = raw if max_total is None else min(raw, max_total)
    return ExtraScore(
        total=total,
        raw_total=raw,
        capped=max_total is not None and raw > max_total,
        max_total=max_total,
        awards=tuple(Award(r) for r in final),
        skipped=tuple(skipped.values()),
        unmatched=tuple(c for i, c in enumerate(claims) if i not in matched),
    )


_KEY = re.compile(r"[^a-z_]")


def clean_kind(value: str) -> str | None:
    """Вид достижения из запроса: только известные значения."""
    kind = _KEY.sub("", value.casefold())
    return kind if kind in KINDS else None
