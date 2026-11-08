"""Разбор порогов ЕГЭ на реальных формулировках из таблиц вузов (T-030)."""

import pytest
from olymp_domain.ege import EgeRequirement, ege_status, parse_ege_requirement, subject_of_profile

R = EgeRequirement


@pytest.mark.parametrize(
    ("subject", "minimum", "expected"),
    [
        # самые частые строки базы
        ("", "", R((), None)),
        ("", "75", R((), 75)),
        ("математика", "75", R(("math",), 75)),
        ("физика", "75", R(("phys",), 75)),
        ("информатика", "75", R(("inf",), 75)),
        ("обществознание", "75", R(("soc",), 75)),
        ("математика", "75 и более", R(("math",), 75)),
        ("история", "75", R(("hist",), 75)),
        ("химия", "75", R(("chem",), 75)),
        ("иностранный язык", "75", R(("foreign",), 75)),
        ("информатика, математика", "75", R(("inf", "math"), 75)),
        ("русский язык", "75", R(("rus",), 75)),
        ("-", "", R((), None)),
        ("информатика/физика/математика", "75", R(("inf", "phys", "math"), 75)),
        ("математика/информатика", "75", R(("math", "inf"), 75)),
        ("биология", "75", R(("bio",), 75)),
        ("литература", "75 и более", R(("lit",), 75)),
        ("география", "75", R(("geo",), 75)),
        # регистр, ИКТ, пробелы вместо запятых и переносы внутри слов
        ("Информатика, физика", "75", R(("inf", "phys"), 75)),
        ("информатика и ИКТ", "75", R(("inf",), 75)),
        ("математика, информатика и ИКТ", "75", R(("math", "inf"), 75)),
        ("Информатика ИКТ Физика", "", R(("inf", "phys"), None)),
        ("Информатика и ИКТ Физика", "", R(("inf", "phys"), None)),
        ("физика / информатика", "75 и более", R(("phys", "inf"), 75)),
        ("история/обществозна ние", "75 и более", R(("hist", "soc"), 75)),
        ("математика/информат ика", "75 и более", R(("math", "inf"), 75)),
        ("обществознание, история", "75", R(("soc", "hist"), 75)),
        ("физика и химия", "75", R(("phys", "chem"), 75)),
        ("Математика Обществознание", "", R(("math", "soc"), None)),
        ("обществозанние", "75 и более", R(("soc",), 75)),
        # не ЕГЭ рядом с предметом и другие пороги
        ("собеседование, обществознание", "75", R(("soc",), 75)),
        ("математика", "80 и более", R(("math",), 80)),
        ("информатика", "90 и более", R(("inf",), 90)),
        ("математика", "нет", R(("math",), None)),
        ("-", "-", R((), None)),
    ],
)
def test_real_rows(subject: str, minimum: str, expected: EgeRequirement) -> None:
    assert parse_ege_requirement(subject, minimum) == expected


@pytest.mark.parametrize(
    ("subject", "minimum"),
    [
        ("рисунок", "75"),
        ("экономика", "75 и более"),
        ("компьютерные и информационные науки, информатика и вычислительная техника", "75 и более"),
        ("политические науки и регионоведение", "75 и более"),
        ("Победитель Призер", ""),
        ("математика", "300"),
        ("математика", "75 или 80"),
    ],
)
def test_not_parsed_is_none(subject: str, minimum: str) -> None:
    assert parse_ege_requirement(subject, minimum) is None


def test_none_inputs() -> None:
    assert parse_ege_requirement(None, None) == R((), None)


@pytest.mark.parametrize(
    ("profile", "subject"),
    [
        ("математика", "math"),
        ("информатика и программирование", "inf"),
        ("английский язык", "foreign"),
        ("русский язык", "rus"),
        ("физика", "phys"),
        ("инженерные науки", None),
        ("", None),
    ],
)
def test_subject_of_profile(profile: str, subject: str | None) -> None:
    assert subject_of_profile(profile) == subject


def test_status() -> None:
    either = R(("inf", "math"), 75)
    assert ege_status(either, {"math": 82}, None) == ("confirmed", None, ("inf", "math"))
    # из нескольких предметов берётся лучший балл
    assert ege_status(either, {"inf": 70, "math": 72}, None) == ("short", 3, ("inf", "math"))
    assert ege_status(either, {"phys": 99}, None) == ("missing_score", None, ("inf", "math"))
    # предмет не указан — по профилю олимпиады
    assert ege_status(R((), 75), {"phys": 80}, "phys") == ("confirmed", None, ("phys",))
    assert ege_status(R((), 75), {"phys": 80}, None) == ("missing_score", None, ())
    assert ege_status(R(("math",), None), {"math": 50}, None) == ("no_threshold", None, ())
    assert ege_status(None, {"math": 50}, "math") == ("no_threshold", None, ())
