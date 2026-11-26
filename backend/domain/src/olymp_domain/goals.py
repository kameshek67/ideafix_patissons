"""Цель из 1–3 направлений: какие олимпиады (с профилем) дают льготу сразу по нескольким.

Чистая функция над строками «льгота направления ↔ олимпиада + профиль»; SQL — в API.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from .diplomas import (
    RULES_2027_FROM_YEAR,
    VSOSH_KEY,
    Change,
    Diploma,
    Role,
    bvi_change,
    roles_allowed,
)

BVI = "БВИ"
HUNDRED = "100 баллов"

Who = Literal["winners", "winners_prizes", "team", "unknown"]
# ключ пары «олимпиада + профиль»; профиль None — льгота дана за олимпиаду целиком
PairKey = tuple[int, int | None]


@dataclass(frozen=True)
class PairInfo:
    """Сама пара: что про неё известно независимо от направлений."""

    olympiad_id: int
    profile_id: int | None
    name: str
    level: str
    # в перечне РСОШ на 2026/27 (для ВсОШ и международных перечень не применим — True)
    in_list: bool
    kind: str = "rsosh"
    # ключ олимпиады в базе: по нему определяем ВсОШ (kind="vsosh" и у ВОШ ЛНР/ДНР)
    olympiad_key: str = ""

    @property
    def key(self) -> PairKey:
        return (self.olympiad_id, self.profile_id)


@dataclass(frozen=True)
class GoalLink:
    """Строка льготы одного направления цели, привязанная к паре."""

    pair: PairKey
    program_id: int
    benefit_type: str
    role: str
    confirm_subject: str = ""
    min_score: int | None = None
    # у правила вуза есть профильный предмет ЕГЭ (нужно для «100 баллов» по правилам 2027)
    has_subject: bool = False


@dataclass
class GoalItem:
    pair: PairInfo
    # направления, где пара даёт БВИ; и где только 100 баллов (БВИ у направления лучше)
    bvi_programs: list[int] = field(default_factory=list)
    hundred_programs: list[int] = field(default_factory=list)
    # направления, где льгота положена и призёрам
    prize_programs: list[int] = field(default_factory=list)
    who: Who = "winners"
    ege_subject: str = ""
    ege_min_score: int | None = None
    prize_hundred_2027: bool = False

    @property
    def coverage(self) -> int:
        return len(self.bvi_programs) + len(self.hundred_programs)


def level_rank(level: str) -> int:
    return {"I": 0, "II": 1, "III": 2}.get(level.strip().upper(), 3)


def _roles(link: GoalLink) -> frozenset[Role]:
    if not link.role.strip():
        return frozenset()
    return roles_allowed(link.role) or frozenset()


def _who(links: list[GoalLink]) -> Who:
    roles = [_roles(link) for link in links]
    if any(Role.PRIZE in r for r in roles):
        return "winners_prizes"
    if any(Role.WINNER in r for r in roles):
        return "winners"
    if any(not link.role.strip() for link in links):
        return "unknown"
    return "team"


def _prize_hundred_2027(pair: PairInfo, links: list[GoalLink]) -> bool:
    """По проекту правил 2027 призёру БВИ заменят на 100 баллов — хотя бы по одному направлению."""
    diploma = Diploma(
        olympiad_id=pair.olympiad_id,
        profile_id=pair.profile_id,
        profile_keys=frozenset(),
        role=Role.PRIZE,
        grade=None,
        year=RULES_2027_FROM_YEAR,
        international=pair.kind == "international",
        vsosh=pair.olympiad_key == VSOSH_KEY,
    )
    return any(
        bvi_change([diploma], link.has_subject) is Change.HUNDRED
        for link in links
        if link.benefit_type == BVI and Role.PRIZE in _roles(link)
    )


def build_goal(pairs: dict[PairKey, PairInfo], links: list[GoalLink]) -> list[GoalItem]:
    """Пары, дающие БВИ или 100 баллов по выбранным направлениям, в порядке полезности.

    Сначала пары из перечня 2026/27 (вне перечня — в конце), затем те, что покрывают больше
    направлений; БВИ раньше 100 баллов; доступнее (призёрам тоже); уровень I раньше III.
    """
    by_pair: dict[PairKey, list[GoalLink]] = {}
    for link in links:
        if link.benefit_type in (BVI, HUNDRED) and link.pair in pairs:
            by_pair.setdefault(link.pair, []).append(link)

    items: list[GoalItem] = []
    for key, rows in by_pair.items():
        pair = pairs[key]
        bvi = sorted({r.program_id for r in rows if r.benefit_type == BVI})
        hundred = sorted({r.program_id for r in rows if r.benefit_type == HUNDRED} - set(bvi))
        # порог и предмет — по лучшему виду льготы пары
        best = [r for r in rows if r.benefit_type == (BVI if bvi else HUNDRED)]
        scores = [r.min_score for r in best if r.min_score is not None]
        subjects = Counter(r.confirm_subject.strip() for r in best if r.confirm_subject.strip())
        items.append(
            GoalItem(
                pair=pair,
                bvi_programs=bvi,
                hundred_programs=hundred,
                prize_programs=sorted({r.program_id for r in rows if Role.PRIZE in _roles(r)}),
                who=_who(rows),
                ege_subject=subjects.most_common(1)[0][0] if subjects else "",
                ege_min_score=min(scores) if scores else None,
                prize_hundred_2027=_prize_hundred_2027(pair, rows),
            )
        )
    items.sort(
        key=lambda i: (
            not i.pair.in_list,
            -i.coverage,
            -len(i.bvi_programs),
            -len(i.prize_programs),
            level_rank(i.pair.level),
            i.pair.name.lower(),
        )
    )
    return items
