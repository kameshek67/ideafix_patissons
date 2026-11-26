"""Подбор льгот по дипломам ученика: подходит ли строка таблицы вуза к конкретному диплому.

Чистая логика без базы. Диплом — олимпиада, профиль (или предмет), степень, класс и год.
Строка льготы — то, что вуз написал в колонках «Профиль», «Кому», «Класс», «Годы». Ответ —
подходит ли строка и насколько уверенно, или почему нет.

Диплом передаётся в API строкой вида ``высшаяпроба.математика.w.11.2025``:
ключ олимпиады, ключ профиля (``-`` — профиль не указан), степень (``w`` — победитель,
``p`` — призёр), класс (``0`` — не указан) и год олимпиады (``0`` — не указан). У ВсОШ
после года может идти этап: ``r`` — региональный, ``f`` или ничего — заключительный. Ключи —
``squash`` названий, они не меняются при пересборке базы (в отличие от id).
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from .textutils import squash

# Год данных: приёмная кампания, по которой собраны правила вузов.
CAMPAIGN_YEAR = 2026
# Год поступления ученика по умолчанию (настройка API OLYMP_ADMISSION_YEAR).
ADMISSION_YEAR = 2027
# Первый год олимпиады, к которому применяют новые нормы: сезон 2026/27, год окончания.
RULES_2027_FROM_YEAR = 2027
# Ключ ВсОШ в строке диплома (squash названия): только у неё выбирают этап.
VSOSH_KEY = "всероссийскаяолимпиадашкольников"


def diploma_years(admission_year: int = ADMISSION_YEAR) -> tuple[int, ...]:
    """Годы олимпиад, дипломы которых действуют при поступлении в admission_year.

    Диплом действует четыре года, включая текущий учебный год: для поступления в 2027 —
    олимпиады 2024–2027 (для сезона «2026/27» считается год окончания — 2027).
    """
    return tuple(range(admission_year - 3, admission_year + 1))


GRADES: tuple[int, ...] = (9, 10, 11)
MAX_DIPLOMAS = 20


class Role(StrEnum):
    WINNER = "w"
    PRIZE = "p"


class Stage(StrEnum):
    """Этап ВсОШ: льготы даёт только заключительный."""

    FINAL = "f"
    REGIONAL = "r"


class Fit(StrEnum):
    """Насколько уверенно строка подходит к диплому."""

    EXACT = "exact"  # профиль строки — профиль диплома (или у олимпиады нет профилей)
    SUBJECT = "subject"  # профиль в строке не указан, но совпал предмет (часто у ВсОШ)
    CHECK = "check"  # профиль в строке не указан — соответствие направлению проверить в правилах
    ROLE = "role"  # в строке не указано, кому льгота: призёру — проверить, не только ли победителям


class Reject(StrEnum):
    """Почему строка олимпиады диплома не подошла."""

    PROFILE = "profile"  # другой профиль или предмет — это просто не та строка
    ROLE = "role"  # нужен диплом победителя
    GRADE = "grade"  # диплом за другой класс
    YEAR = "year"  # диплом другого года (или уже не действует)
    TEAM = "team"  # только для членов сборных команд
    STAGE = "stage"  # региональный этап ВсОШ льгот не даёт
    NEW_GRADE = "new_grade"  # по проекту 2027 учитываются дипломы 10–11 класса


class Rules(StrEnum):
    """По каким правилам считать льготы призёров."""

    CURRENT = "current"
    PROJECT_2027 = "project2027"


FIT_ORDER = {Fit.EXACT: 0, Fit.SUBJECT: 1, Fit.CHECK: 2, Fit.ROLE: 3}


def is_sure(fit: Fit) -> bool:
    """Строка подошла уверенно: профиль или предмет совпали и роль не под вопросом."""
    return fit in (Fit.EXACT, Fit.SUBJECT)


# ---------------------------------------------------------------- строка диплома

RE_SPEC = re.compile(r"^([^\W\d_]+)\.([^\W\d_]+|-)\.([wp])\.(0|9|10|11)\.(0|20\d\d)(?:\.([fr]))?$")


@dataclass(frozen=True)
class DiplomaSpec:
    olympiad_key: str
    profile_key: str | None
    role: Role
    grade: int | None
    year: int | None
    stage: Stage = Stage.FINAL

    @classmethod
    def parse(cls, value: str) -> "DiplomaSpec":
        m = RE_SPEC.match(value.strip().lower().replace("ё", "е"))
        if not m:
            raise ValueError(f"Диплом в неверном формате: {value!r}")
        olympiad, profile, role, grade, year, stage = m.groups()
        if stage == Stage.REGIONAL and olympiad != VSOSH_KEY:
            raise ValueError(f"Этап указывается только для ВсОШ: {value!r}")
        return cls(
            olympiad_key=olympiad,
            profile_key=None if profile == "-" else profile,
            role=Role(role),
            grade=int(grade) or None,
            year=int(year) or None,
            stage=Stage(stage or Stage.FINAL),
        )

    def __str__(self) -> str:
        parts = [
            self.olympiad_key,
            self.profile_key or "-",
            self.role.value,
            str(self.grade or 0),
            str(self.year or 0),
        ]
        # заключительный этап в строке не пишется: ключи прежних дипломов не меняются
        if self.stage is not Stage.FINAL:
            parts.append(self.stage.value)
        return ".".join(parts)

    def expired(self, admission_year: int = ADMISSION_YEAR) -> bool:
        """Диплом слишком старый (или из будущего) для года поступления."""
        return self.year is not None and self.year not in diploma_years(admission_year)


# ---------------------------------------------------------------- условия строки


def roles_allowed(text: str) -> frozenset[Role] | None:
    """Кому из обладателей дипломов положена льгота. None — только членам сборных команд.

    «Только победители» / «победители» — только победителям. «Призёры» без победителей
    оставляем и победителям: у вузов такие строки идут рядом со строкой для победителей,
    а скрыть льготу хуже, чем показать лишнюю. Пустая колонка — условие не указано.
    """
    t = text.lower().replace("ё", "е")
    if "сборн" in t and "победител" not in t and "призер" not in t:
        return None
    if "победител" in t and "призер" not in t:
        return frozenset({Role.WINNER})
    return frozenset({Role.WINNER, Role.PRIZE})


RE_GRADE_RANGE = re.compile(r"(?<!\d)(9|10|11)\s*[-–—]\s*(9|10|11)(?!\d)")
RE_GRADE_ONE = re.compile(r"(?<!\d)(9|10|11)(?!\d)")


def grades_allowed(grade: str, role: str = "") -> frozenset[int]:
    """Классы, за которые засчитывается диплом; пустое множество — без ограничения.

    Берётся колонка «Класс» («10, 11 класс», «класс 10-11», «только за 11 класс») и уточнение
    в колонке «Кому» («победители и призёры (10–11 класс)»).
    """
    found: set[int] = set()
    for text in (grade, role if "класс" in role.lower() else ""):
        for start, end in RE_GRADE_RANGE.findall(text):
            found.update(range(int(start), int(end) + 1))
        found.update(int(g) for g in RE_GRADE_ONE.findall(text))
    return frozenset(found)


RE_YEARS = re.compile(r"(?<!\d)(20\d\d)\s*([-–—/])\s*(\d{4}|\d{2})(?!\d)")
RE_YEAR = re.compile(r"(?<!\d)20\d\d(?!\d)")


def years_allowed(text: str) -> frozenset[int]:
    """Годы олимпиад, дипломы которых принимаются; пустое множество — по общему правилу.

    «2023, 2024» — годы; «2024/25», «2024-25» и «2024/2025» — сезон, год окончания;
    «2023–2026» — диапазон из двух четырёхзначных годов.
    """
    found: set[int] = set()
    for start, sep, end in RE_YEARS.findall(text):
        if sep == "/" or len(end) == 2:
            found.add(int(end) if len(end) == 4 else int(start[:2] + end))
        else:
            found.update(range(int(start), int(end) + 1))
    found.update(int(y) for y in RE_YEAR.findall(RE_YEARS.sub(" ", text)))
    return frozenset(found)


RE_PARENS = re.compile(r"\([^)]*\)")
RE_SUBJECT_SPLIT = re.compile(r"[,;:]")
EMPTY_SUBJECTS = frozenset({"", "нет"})


def subject_keys(text: str) -> frozenset[str]:
    """Ключи предметов из колонки «Предмет»: «информатика, математика, труд (технология)».

    Каждый предмет даёт два ключа — целиком и без уточнения в скобках, чтобы «Труд
    (технология)» совпал и с «труд», и с «трудтехнология».
    """
    keys: set[str] = set()
    for variant in (text, RE_PARENS.sub(" ", text)):
        for part in RE_SUBJECT_SPLIT.split(variant):
            key = squash(part)
            if key not in EMPTY_SUBJECTS:
                keys.add(key)
    return frozenset(keys)


def profile_keys(name: str) -> frozenset[str]:
    """Ключи профиля диплома для сравнения с предметами строк без профиля.

    Иностранные языки у ВсОШ — отдельные профили («английский язык»), а в таблицах вузов
    часто записаны общим «иностранный язык».
    """
    keys = set(subject_keys(name))
    if any(k.endswith("язык") and k != "русскийязык" for k in keys):
        keys.add("иностранныйязык")
    return frozenset(keys)


# Мусор разбора таблиц среди профилей: обрывки фраз вместо названий профилей
RE_JUNK_PROFILE = re.compile(
    r"^(бви\b|баллов$|профил[ьи]\s*:|анкета|на конкретную|для\s|нет$|-+$)|не предусмотрено",
    re.IGNORECASE,
)


def is_real_profile(name: str) -> bool:
    """Профиль, который ученик может выбрать в форме диплома."""
    return bool(squash(name)) and not RE_JUNK_PROFILE.search(name.strip())


# ---------------------------------------------------------------- сопоставление


@dataclass(frozen=True)
class Diploma:
    """Диплом, привязанный к текущей базе (id вместо ключей)."""

    olympiad_id: int
    profile_id: int | None
    profile_keys: frozenset[str]
    role: Role
    grade: int | None
    year: int | None
    stage: Stage = Stage.FINAL
    # международная олимпиада: диплом у участника сборной, поэтому льготы «членам сборных» ему подходят
    international: bool = False
    # диплом ВсОШ: проект 2027 её не затрагивает
    vsosh: bool = False


@dataclass(frozen=True)
class Link:
    """Строка льготы, привязанная к олимпиаде, — только поля, нужные для проверки."""

    olympiad_id: int
    profile_id: int | None
    subject: str
    role: str
    grade: str
    years: str


def match(
    diploma: Diploma,
    link: Link,
    admission_year: int = ADMISSION_YEAR,
    rules: Rules = Rules.CURRENT,
) -> Fit | Reject:
    """Подходит ли строка к диплому: сначала профиль, потом степень, класс и год.

    По проекту 2027 дипломы 9 класса олимпиад 2026/27 и позже льгот не дают.
    """
    if link.olympiad_id != diploma.olympiad_id:
        return Reject.PROFILE
    if diploma.stage is Stage.REGIONAL:
        return Reject.STAGE
    if (
        rules is Rules.PROJECT_2027
        and diploma.grade == 9
        and diploma.year is not None
        and diploma.year >= RULES_2027_FROM_YEAR
    ):
        return Reject.NEW_GRADE

    subjects = subject_keys(link.subject)
    fit: Fit
    if link.profile_id is not None:
        if diploma.profile_id is None:
            fit = Fit.CHECK
        elif link.profile_id == diploma.profile_id:
            fit = Fit.EXACT
        else:
            return Reject.PROFILE
    elif subjects:
        if diploma.profile_id is None:
            fit = Fit.CHECK
        elif subjects & diploma.profile_keys:
            fit = Fit.SUBJECT
        else:
            return Reject.PROFILE
    else:
        # строка про олимпиаду целиком: у олимпиады без профилей это точное совпадение
        fit = Fit.EXACT if diploma.profile_id is None and not diploma.profile_keys else Fit.CHECK

    roles = roles_allowed(link.role)
    if roles is None:
        if not diploma.international:
            return Reject.TEAM
        roles = frozenset(Role)
    if diploma.role not in roles:
        return Reject.ROLE

    grades = grades_allowed(link.grade, link.role)
    if diploma.grade is not None and grades and diploma.grade not in grades:
        return Reject.GRADE

    years = years_allowed(link.years)
    if diploma.year is not None and (
        diploma.year not in diploma_years(admission_year) or (years and diploma.year not in years)
    ):
        return Reject.YEAR
    # вуз не написал «кому»: победителю подходит, призёру — проверить, не только ли победителям
    if not link.role.strip() and diploma.role is Role.PRIZE:
        return Fit.ROLE
    return fit


def better(a: Fit, b: Fit) -> Fit:
    return a if FIT_ORDER[a] <= FIT_ORDER[b] else b


# ---------------------------------------------------------------- правила 2027 (проект)


class Change(StrEnum):
    """Что правила 2027 делают со строкой БВИ."""

    HUNDRED = "hundred"  # БВИ превращается в «100 баллов» по профильному предмету
    CHECK = "check"  # может измениться — проверить в правилах вуза


def prize_change(diploma: Diploma) -> Change | None:
    """Что правила 2027 меняют для БВИ по этому диплому; None — ничего.

    БВИ остаётся у победителей, у ВсОШ и у международных олимпиад. Призёрам перечневых
    олимпиад БВИ заменяют на 100 баллов, но только за олимпиады 2026/27 и позже: дипломы
    прежних лет вузы учитывают по прежним правилам. Год диплома не указан — проверить.
    """
    if diploma.role is not Role.PRIZE or diploma.vsosh or diploma.international:
        return None
    if diploma.year is None:
        return Change.CHECK
    return Change.HUNDRED if diploma.year >= RULES_2027_FROM_YEAR else None


def bvi_change(diplomas: list[Diploma], has_subject: bool) -> Change | None:
    """Судьба строки БВИ, которую дают эти дипломы вместе: хоть один диплом без изменений —
    БВИ остаётся. «100 баллов» только если у вуза по направлению есть профильный предмет ЕГЭ,
    иначе — проверить."""
    changes = [prize_change(d) for d in diplomas]
    if not changes or None in changes:
        return None
    if Change.CHECK in changes or not has_subject:
        return Change.CHECK
    return Change.HUNDRED
