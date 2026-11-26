import pytest
from olymp_domain import squash
from olymp_domain.profile_query import collapse_profiles, match_profiles, split_query


def profile(pid: int, name: str, mentions: int, level_2026_27: str = "") -> dict:
    return {"id": pid, "name": name, "mentions": mentions, "level_2026_27": level_2026_27}


NTO = [
    profile(1, "искусственный интеллект", 218, "II"),
    profile(2, "большие данные и машинное обучение", 220, "III"),
    profile(3, "автономные транспортные системы", 183, "II"),
    profile(4, "автономные транспортные системы беспилотный", 79),
    profile(5, "разработка мобильных приложений", 122, "III"),
    profile(6, "разработка мобильных предложений", 134),
    profile(7, "беспилотный транспорт: аэрокосмические системы, летающая робототехника", 148),
    profile(8, "летающая", 1),
    profile(9, "информационная безопасность", 205, "III"),
    profile(10, "умный город", 105),
    profile(11, "умные системы и технологии: умный город, цифровые сенсорные системы", 114),
    profile(12, "виртуальный профиль без строк", 0),
    profile(13, "математика", 1),
]


def test_collapse_hides_junk_and_keeps_real_profiles() -> None:
    visible, merged = collapse_profiles(NTO)
    names = {p["name"] for p in visible}
    assert "летающая" not in names  # обрыв названия
    assert "автономные транспортные системы беспилотный" not in names  # склейка с обрывом
    assert "разработка мобильных предложений" not in names  # опечатка, уровень у «приложений»
    assert "виртуальный профиль без строк" not in names  # нет строк льгот
    assert {"умный город", "математика", "разработка мобильных приложений"} <= names
    assert merged[7] == [8] and merged[3] == [4] and merged[5] == [6]


def test_collapse_keeps_selected_profile_and_does_not_touch_input() -> None:
    before = [dict(p) for p in NTO]
    visible, merged = collapse_profiles(NTO, keep=[8])
    assert 8 in {p["id"] for p in visible} and 7 not in merged
    assert before == NTO


def test_collapse_without_profiles() -> None:
    assert collapse_profiles([]) == ([], {})


@pytest.mark.parametrize(
    ("rest", "expected"),
    [
        ("ии", "искусственный интеллект"),
        ("искусственный интеллект", "искусственный интеллект"),
        ("интеллект", "искусственный интеллект"),
        ("иб", "информационная безопасность"),
        ("безопасность", "информационная безопасность"),
        ("мобильные", "разработка мобильных приложений"),
        ("машинное обучение", "большие данные и машинное обучение"),
        ("бпла", "беспилотный транспорт: аэрокосмические системы, летающая робототехника"),
    ],
)
def test_match_profiles_finds_best(rest: str, expected: str) -> None:
    visible, _ = collapse_profiles(NTO)
    hits = match_profiles(rest, visible)
    assert hits and hits[0][0]["name"] == expected


def test_match_profiles_ignores_noise() -> None:
    visible, _ = collapse_profiles(NTO)
    assert match_profiles("я", visible) == []
    assert match_profiles("кулинария", visible) == []


def test_match_profiles_does_not_search_inside_lists() -> None:
    lists = [profile(1, "математика, физика, НТО (все профили)", 5)]
    assert match_profiles("нто", lists) == []
    assert match_profiles("математика", lists)


@pytest.mark.parametrize(
    ("query", "rest"),
    [
        ("нто ии", "ии"),
        ("ии нто", "ии"),
        ("высшая проба матем", "матем"),
        ("НТО: искусственный интеллект", "искусственныйинтеллект"),
    ],
)
def test_split_query_both_sides(query: str, rest: str) -> None:
    aliases = [(1, "нто"), (2, "высшаяпроба"), (3, "искусственныйинтеллект")]
    pairs = dict(split_query(squash(query), aliases)).items()
    assert (1, rest) in pairs or (2, rest) in pairs


def test_split_query_needs_a_rest() -> None:
    assert split_query("нто", [(1, "нто")]) == []
    assert split_query("нтои", [(1, "нто")]) == []
