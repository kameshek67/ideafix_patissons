"""Условия льготы для модели: строка базы -> короткая строка текста и поиск расхождений.

Чистые функции без базы и сети. Модель раньше видела только вид льготы («БВИ»), поэтому
отвечала «порога ЕГЭ в базе нет». Теперь каждая строка несёт «кому, класс, предмет, порог».
Поля строк приходят из документов вузов и считаются недоверенными данными: длина ограничена.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from olymp_domain.interests import display_name

BENEFIT_RANK = {"БВИ": 0, "100 баллов": 1, "Особое право (БВИ/100)": 2, "Фаст-трек": 3}
CONFLICT_NOTE = "в документах вуза несколько условий — проверь по источнику"
DIVERGE_MARK = "условия расходятся с другой строкой"
BY_PROFILE_MARK = "по профилю"
BY_PROFILE_LEGEND = (
    "«по профилю» — вуз эту олимпиаду прямо не называет: льгота выведена из его правила «любая "
    "олимпиада перечня с таким профилем»"
)
DATA_YEAR = 2026
DATA_NOTICE = (
    "Данные приёмной кампании 2026. Правила на 2027 год вуз публикует на сайте не позднее "
    "20 января 2027: до этого условия могут измениться."
)

RE_NUMBER = re.compile(r"\d+")
RE_RANGE = re.compile(r"(\d+)\s*[-–—]\s*(\d+)")
RE_BRACKETS = re.compile(r"\(.*?\)")
NO_THRESHOLD = frozenset({"нет", "-", "—", "–"})


def squeeze(value: Any, limit: int) -> str:
    """Одна строка без лишних пробелов и не длиннее limit символов."""
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def grade_key(grade: str) -> tuple[int, ...]:
    """Классы числами: «10, 11 класс» и «класс 10-11» — одно и то же."""
    found = {int(n) for n in RE_NUMBER.findall(grade)}
    for low, high in RE_RANGE.findall(grade):
        found.update(range(int(low), int(high) + 1))
    return tuple(sorted(found))


def short_years(years: str) -> str:
    """«2023, 2024, 2025, 2026» -> «2023–2026»: короче, смысл тот же."""
    found = sorted({int(n) for n in RE_NUMBER.findall(years) if len(n) == 4})
    if len(found) >= 3 and found == list(range(found[0], found[-1] + 1)):
        return f"{found[0]}–{found[-1]}"
    return years


def role_key(role: str) -> str:
    return " ".join(RE_BRACKETS.sub("", role).lower().split())


@dataclass(frozen=True)
class Condition:
    """Одна строка условий. Равные по полям строки считаются одной (дубли убираются)."""

    kind: str
    profile: str
    role: str
    grade: str
    subject: str
    min_ege: str  # число баллов или пусто
    no_threshold: bool
    award: str
    level: str
    years: str
    derived: bool

    @classmethod
    def from_benefit(cls, benefit: dict[str, Any]) -> "Condition":
        matched = benefit.get("matched") or {}
        raw_ege = squeeze(benefit.get("min_ege"), 40).lower()
        number = RE_NUMBER.search(raw_ege)
        profile = matched.get("profile") or benefit.get("olympiad_profile")
        return cls(
            kind=squeeze(benefit.get("benefit_type"), 40),
            profile=display_name(squeeze(profile, 60)),
            role=squeeze(benefit.get("winner_role"), 90),
            grade=squeeze(benefit.get("grade"), 40),
            subject=squeeze(benefit.get("confirm_subject"), 60),
            min_ege=number.group(0) if number else "",
            no_threshold=not number and raw_ege in NO_THRESHOLD,
            award=squeeze(benefit.get("award_subject"), 30),
            level=squeeze(benefit.get("level"), 12),
            years=short_years(squeeze(benefit.get("years"), 40)),
            derived=bool(benefit.get("derived")),
        )

    def ege_part(self) -> str:
        if self.subject and self.min_ege:
            return f"подтверждение: ЕГЭ {self.subject} ≥ {self.min_ege}"
        if self.subject:
            return f"подтверждение: ЕГЭ {self.subject}"
        if self.min_ege:
            return f"ЕГЭ ≥ {self.min_ege}"
        return "порога ЕГЭ в документе нет" if self.no_threshold else ""

    def line(self) -> str:
        """Строка для модели: вид · профиль · кому · класс · ЕГЭ · уровень · годы · метка."""
        kind = self.kind
        if self.kind == "100 баллов" and self.award:
            kind = f"100 баллов (ЕГЭ {self.award})"
        parts = [
            kind,
            f"профиль «{self.profile}»" if self.profile else "",
            f"кому: {self.role}" if self.role else "",
            self.grade,
            self.ege_part(),
            f"уровень {self.level}" if self.level else "",
            f"дипломы {self.years}" if self.years else "",
            f"[{BY_PROFILE_MARK}]" if self.derived else "",
        ]
        return " · ".join(part for part in parts if part)

    def group(self) -> tuple[str, str, str]:
        """Что считается одним и тем же условием: вид льготы, профиль, подтверждающий предмет."""
        return self.kind, self.profile.lower(), self.subject.lower()

    def contradicts(self, other: "Condition") -> bool:
        """Условия не могут действовать вместе: оба поля заполнены и значения разные.

        Пустое поле — «не указано», а не «любое». Строки для разных классов («10 класс» и
        «11 класс») друг другу не противоречат: это разные ученики.
        """
        mine, theirs = grade_key(self.grade), grade_key(other.grade)
        if mine and theirs and not set(mine) & set(theirs):
            return False
        pairs = ((role_key(self.role), role_key(other.role)), (self.min_ege, other.min_ege))
        return any(a and b and a != b for a, b in pairs)


def diverging(conditions: Iterable[Condition]) -> set[Condition]:
    """Строки одной группы (вид льготы × профиль × предмет), которые друг другу противоречат.

    Так бывает, когда в документах вуза для одного и того же случая записаны разные условия
    («только победители 11 класса, ЕГЭ ≥ 85» и «победители и призёры, ≥ 75»). Выбирать одно из
    них молча нельзя: модель получает обе строки и пометку проверить по источнику.
    """
    groups: dict[tuple[str, str, str], list[Condition]] = {}
    for item in dict.fromkeys(conditions):
        groups.setdefault(item.group(), []).append(item)
    flagged: set[Condition] = set()
    for members in groups.values():
        for i, first in enumerate(members):
            for second in members[i + 1 :]:
                if first.contradicts(second):
                    flagged.update((first, second))
    return flagged


@dataclass
class Summary:
    lines: list[str]
    conflict: bool = False
    more: int = 0  # строк условий, не вошедших в lines
    by_profile: bool = False  # среди показанных строк есть «по профилю»

    def as_fields(self) -> dict[str, Any]:
        """Поля для JSON: пустые не выводятся, чтобы не тратить размер ответа."""
        fields: dict[str, Any] = {"conditions": self.lines}
        if self.conflict:
            fields["conflict"] = CONFLICT_NOTE
        if self.more:
            fields["more_conditions"] = self.more
        return fields


def summarize(benefits: Sequence[dict[str, Any]], cap: int) -> Summary:
    """Строки условий по набору льгот одной программы (и олимпиады): без дублей, не больше cap.

    Сначала идут строки с расхождениями (их нельзя терять), потом БВИ, потом 100 баллов; строки,
    которые вуз назвал прямо, раньше выведенных «по профилю».
    """
    conditions = [Condition.from_benefit(b) for b in benefits]
    flagged = diverging(conditions)
    unique = list(dict.fromkeys(conditions))
    unique.sort(
        key=lambda c: (
            c not in flagged,
            BENEFIT_RANK.get(c.kind, 9),
            c.derived,
            c.profile,
            c.subject,
            c.line(),
        )
    )
    shown = unique[:cap]
    lines = [c.line() + (f" [{DIVERGE_MARK}]" if c in flagged else "") for c in shown]
    return Summary(
        lines=lines,
        conflict=bool(flagged),
        more=len(unique) - len(shown),
        by_profile=any(c.derived for c in shown),
    )
