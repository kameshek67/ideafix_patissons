"""Пороги ЕГЭ для подтверждения диплома (F-03, T-030).

В таблицах вузов предмет и порог — свободный текст: «информатика/физика/математика» и
«75 и более», «Информатика ИКТ Физика», «обществозна ние» с переносом. parse_ege_requirement
разбирает это в коды предметов и число; неразобранное — None, без исключений.

Если предмет не указан (так в трети строк), подтверждают ЕГЭ по предмету профиля олимпиады —
его даёт subject_of_profile.
"""

import re
from dataclasses import dataclass
from typing import Literal

from .textutils import squash

# код предмета → как он пишется в таблицах (squash: только буквы, нижний регистр)
SUBJECTS: dict[str, tuple[str, ...]] = {
    "rus": ("русскийязык",),
    "math": ("математикапрофильная", "математика"),
    "inf": ("информатикаиикт", "информатикаикт", "информатика"),
    "phys": ("физика",),
    "chem": ("химия",),
    "bio": ("биология",),
    "soc": ("обществознание", "обществозанние", "общкствознание"),  # опечатки из таблиц вузов
    "hist": ("история",),
    "lit": ("литература",),
    "foreign": ("иностранныйязык", "иностранныеязыки"),
    "geo": ("география",),
}
SUBJECT_NAMES = {
    "rus": "русскому языку",
    "math": "математике",
    "inf": "информатике",
    "phys": "физике",
    "chem": "химии",
    "bio": "биологии",
    "soc": "обществознанию",
    "hist": "истории",
    "lit": "литературе",
    "foreign": "иностранному языку",
    "geo": "географии",
}
# слова между предметами и то, что не ЕГЭ, но встречается рядом с предметом
CONNECTORS = ("или", "и")
IGNORED = ("собеседование",)
NO_THRESHOLD = {"", "-", "—", "нет"}

# самые длинные написания первыми: «информатикаиикт» раньше «информатика»
_FORMS = sorted(
    ((form, code) for code, forms in SUBJECTS.items() for form in forms),
    key=lambda pair: -len(pair[0]),
)
_NUMBER = re.compile(r"\d{2,3}")


@dataclass(frozen=True)
class EgeRequirement:
    subjects: tuple[str, ...]  # пусто — предмет не указан (по профилю олимпиады)
    min_score: int | None  # None — порога нет


def parse_subjects(text: str) -> tuple[str, ...] | None:
    """Коды предметов из текста; None — встретилось что-то кроме предметов ЕГЭ."""
    rest = squash(text)
    found: list[str] = []
    while rest:
        for form, code in _FORMS:
            if rest.startswith(form):
                if code not in found:
                    found.append(code)
                rest = rest[len(form) :]
                break
        else:
            skip = next((w for w in (*IGNORED, *CONNECTORS) if rest.startswith(w)), None)
            if skip is None:
                return None
            rest = rest[len(skip) :]
    return tuple(found)


def parse_min_score(text: str) -> int | None | Literal[False]:
    """Порог 40–100; None — порога нет; False — не разобрано."""
    value = (text or "").strip().lower()
    if value in NO_THRESHOLD:
        return None
    numbers = [int(n) for n in _NUMBER.findall(value)]
    if len(numbers) == 1 and 40 <= numbers[0] <= 100:
        return numbers[0]
    return False


def parse_ege_requirement(subject_text: str | None, min_text: str | None) -> EgeRequirement | None:
    """Предметы и порог подтверждения; None — текст не разобран."""
    subject_text = (subject_text or "").strip()
    subjects = () if subject_text in NO_THRESHOLD else parse_subjects(subject_text)
    score = parse_min_score(min_text or "")
    if subjects is None or score is False:
        return None
    return EgeRequirement(subjects=subjects, min_score=score)


def subject_of_profile(profile: str | None) -> str | None:
    """Предмет ЕГЭ для профиля олимпиады, если профиль — школьный предмет («математика»,
    «английский язык», «информатика и программирование»)."""
    key = squash(profile or "")
    if not key:
        return None
    if key.endswith("язык") and key not in ("русскийязык",):
        return "foreign"
    if key in ("информатикаипрограммирование", "программирование", "информатикакомплекс"):
        return "inf"
    subjects = parse_subjects(profile or "")
    return subjects[0] if subjects and len(subjects) == 1 else None


EgeStatus = Literal["confirmed", "short", "missing_score", "no_threshold"]


def ege_status(
    requirement: EgeRequirement | None, scores: dict[str, int], profile_subject: str | None
) -> tuple[EgeStatus, int | None, tuple[str, ...]]:
    """Статус строки льготы по баллам ученика: (статус, сколько не хватает, предметы).

    Из нескольких предметов («информатика или математика») берётся лучший балл.
    """
    if requirement is None or requirement.min_score is None:
        return "no_threshold", None, ()
    subjects = requirement.subjects or ((profile_subject,) if profile_subject else ())
    best = max((scores[s] for s in subjects if s in scores), default=None)
    if best is None:
        return "missing_score", None, subjects
    if best >= requirement.min_score:
        return "confirmed", None, subjects
    return "short", requirement.min_score - best, subjects
