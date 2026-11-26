from typing import Literal

from olymp_api.schemas import ResponseModel


class GoalProgram(ResponseModel):
    id: int
    faculty_or_direction: str
    code: str
    university: str
    university_short: str


class GoalOlympiad(ResponseModel):
    """Олимпиада с профилем и то, что она даёт по выбранным направлениям."""

    olympiad_id: int
    short_name: str
    canonical_name: str
    kind: str
    # None — льгота дана за олимпиаду целиком, без профиля
    profile_id: int | None = None
    profile_name: str = ""
    # направления цели (id), где пара даёт БВИ; и где только 100 баллов
    bvi_programs: list[int]
    hundred_programs: list[int]
    # winners — победителям, winners_prizes — победителям и призёрам, team — членам сборных,
    # unknown — вуз не указал, кому: проверить в правилах вуза
    who: Literal["winners", "winners_prizes", "team", "unknown"]
    # уровень по перечню РСОШ на 2026/27; вне перечня — по документам вузов
    level: str = ""
    in_list_2026_27: bool
    ege_subject: str = ""
    ege_min_score: int | None = None
    # по проекту правил 2027 призёру БВИ заменят на 100 баллов
    prize_hundred_2027: bool = False


class GoalOlympiads(ResponseModel):
    programs: list[GoalProgram]
    items: list[GoalOlympiad]
