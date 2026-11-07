"""Сопоставление диплома со строками таблиц вузов. Формулировки взяты из базы как есть."""

import pytest
from olymp_domain.diplomas import (
    DIPLOMA_YEARS,
    Diploma,
    DiplomaSpec,
    Fit,
    Link,
    Reject,
    Role,
    better,
    grades_allowed,
    is_real_profile,
    match,
    profile_keys,
    roles_allowed,
    subject_keys,
    years_allowed,
)


def test_spec_round_trip() -> None:
    spec = DiplomaSpec.parse("высшаяпроба.математика.w.11.2025")
    assert spec == DiplomaSpec("высшаяпроба", "математика", Role.WINNER, 11, 2025)
    assert str(spec) == "высшаяпроба.математика.w.11.2025"
    empty = DiplomaSpec.parse("нто.-.p.0.0")
    assert (empty.profile_key, empty.grade, empty.year) == (None, None, None)
    assert str(empty) == "нто.-.p.0.0"
    # ключи — squash названий, поэтому «ё» и регистр не мешают
    assert DiplomaSpec.parse("ВсОШ.Химия.P.9.2024").olympiad_key == "всош"


@pytest.mark.parametrize(
    "value",
    ["", "всош", "всош.химия.x.11.2025", "всош.химия.w.8.2025", "всош.химия.w.11.25", "1.2.w.0.0"],
)
def test_spec_rejects_garbage(value: str) -> None:
    with pytest.raises(ValueError):
        DiplomaSpec.parse(value)


def test_spec_expired() -> None:
    assert DIPLOMA_YEARS == (2023, 2024, 2025, 2026)
    assert DiplomaSpec.parse("всош.химия.w.11.2021").expired
    assert not DiplomaSpec.parse("всош.химия.w.11.2023").expired
    assert not DiplomaSpec.parse("всош.химия.w.11.0").expired


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("победители и призёры", {Role.WINNER, Role.PRIZE}),
        ("только победители", {Role.WINNER}),
        ("победители", {Role.WINNER}),
        ("призёры", {Role.WINNER, Role.PRIZE}),
        ("победители и призёры (10–11 класс)", {Role.WINNER, Role.PRIZE}),
        ("", {Role.WINNER, Role.PRIZE}),
    ],
)
def test_roles(text: str, expected: set[Role]) -> None:
    assert roles_allowed(text) == expected


def test_roles_team_only() -> None:
    assert roles_allowed("члены сборных команд РФ") is None


@pytest.mark.parametrize(
    ("grade", "role", "expected"),
    [
        ("11 класс", "", {11}),
        ("10, 11 класс", "", {10, 11}),
        ("10,11 класс", "", {10, 11}),
        ("9, 10, 11 класс", "", {9, 10, 11}),
        ("класс 10-11", "", {10, 11}),
        ("для перечневых — только за 11 класс", "", {11}),
        ("", "победители и призёры (10–11 класс)", {10, 11}),
        ("", "победители и призёры", set()),
        ("", "", set()),
    ],
)
def test_grades(grade: str, role: str, expected: set[int]) -> None:
    assert grades_allowed(grade, role) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2023, 2024, 2025, 2026", {2023, 2024, 2025, 2026}),
        ("2025/26", {2026}),
        ("2025/2026", {2026}),
        ("2024/25, 2025/26", {2025, 2026}),
        ("2021/2022, 2022/2023", {2022, 2023}),
        ("2023", {2023}),
        ("", set()),
    ],
)
def test_years(text: str, expected: set[int]) -> None:
    assert years_allowed(text) == expected


def test_subject_keys() -> None:
    assert subject_keys("Математика") == {"математика"}
    assert subject_keys("информатика, математика, труд (технология), физика") >= {
        "информатика",
        "математика",
        "труд",
        "трудтехнология",
        "физика",
    }
    assert "физика" not in subject_keys("Астрономия (предоставляется 100 баллов по физике)")
    assert "информатика" in subject_keys(
        "Для дипломов 2026 года выдачи: Информатика (профиль программирование); "
        "для дипломов, выданных ранее 2026 года: Информатика"
    )
    assert subject_keys("-") == set() and subject_keys("нет") == set() and subject_keys("") == set()


def test_foreign_language_alias() -> None:
    assert "иностранныйязык" in profile_keys("английский язык")
    assert "иностранныйязык" not in profile_keys("русский язык")


@pytest.mark.parametrize(
    "name", ["баллов", "профили: нет", "БВИ по ВсОШ не предусмотрено", "на конкретную программу"]
)
def test_junk_profiles(name: str) -> None:
    assert not is_real_profile(name)


@pytest.mark.parametrize(
    "name", ["математика", "интеллектуальные робототехнические системы", "ИБ, робототехника"]
)
def test_real_profiles(name: str) -> None:
    assert is_real_profile(name)


# ---------------------------------------------------------------- match

MATH = Diploma(
    olympiad_id=1,
    profile_id=10,
    profile_keys=profile_keys("математика"),
    role=Role.PRIZE,
    grade=11,
    year=2025,
)


def link(**kw: object) -> Link:
    base: dict[str, object] = {
        "olympiad_id": 1,
        "profile_id": 10,
        "subject": "",
        "role": "победители и призёры",
        "grade": "",
        "years": "",
    }
    base.update(kw)
    return Link(**base)  # type: ignore[arg-type]


def test_match_exact_profile() -> None:
    assert match(MATH, link()) is Fit.EXACT


def test_match_other_olympiad_or_profile() -> None:
    assert match(MATH, link(olympiad_id=2)) is Reject.PROFILE
    assert match(MATH, link(profile_id=11)) is Reject.PROFILE


def test_match_by_subject_when_row_has_no_profile() -> None:
    assert match(MATH, link(profile_id=None, subject="Математика")) is Fit.SUBJECT
    assert match(MATH, link(profile_id=None, subject="информатика, математика")) is Fit.SUBJECT
    assert match(MATH, link(profile_id=None, subject="Физика")) is Reject.PROFILE


def test_match_row_without_profile_needs_check() -> None:
    assert match(MATH, link(profile_id=None)) is Fit.CHECK


def test_match_olympiad_without_profiles() -> None:
    whole = Diploma(1, None, frozenset(), Role.WINNER, None, None)
    assert match(whole, link(profile_id=None)) is Fit.EXACT
    # профиль в дипломе не выбран, а строка про конкретный профиль
    assert match(whole, link()) is Fit.CHECK


def test_match_role_grade_year() -> None:
    assert match(MATH, link(role="только победители")) is Reject.ROLE
    assert match(MATH, link(role="члены сборных команд РФ")) is Reject.TEAM
    assert match(MATH, link(grade="10 класс")) is Reject.GRADE
    assert match(MATH, link(grade="10, 11 класс")) is Fit.EXACT
    assert match(MATH, link(years="2023, 2024")) is Reject.YEAR
    assert match(MATH, link(years="2024/25, 2025/26")) is Fit.EXACT


def test_match_unknown_grade_and_year_do_not_filter() -> None:
    unknown = Diploma(1, 10, profile_keys("математика"), Role.PRIZE, None, None)
    assert match(unknown, link(grade="11 класс", years="2023")) is Fit.EXACT


def test_old_diploma_expires_by_default() -> None:
    old = Diploma(1, 10, profile_keys("математика"), Role.WINNER, 11, 2021)
    assert match(old, link()) is Reject.YEAR
    # вуз сам перечислил старые сезоны — значит, принимает
    assert match(old, link(years="2020/2021, 2021/2022")) is Fit.EXACT


def test_better() -> None:
    assert better(Fit.CHECK, Fit.EXACT) is Fit.EXACT
    assert better(Fit.SUBJECT, Fit.CHECK) is Fit.SUBJECT
