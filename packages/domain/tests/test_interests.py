"""Сопоставление тем ученика с названиями профилей олимпиад."""

from olymp_domain.interests import (
    display_name,
    is_list_profile,
    phrase_matches,
    query_words,
    word_matches,
    words_of,
)


def matches(theme: str, profile: str) -> bool:
    return phrase_matches(query_words(theme), words_of(profile))


def test_phrase_matches_any_order_and_endings() -> None:
    profile = "разработка мобильных приложений"
    assert matches("мобильная разработка", profile)
    assert matches("мобильные приложения", profile)
    assert matches("приложения для телефона мобильн", profile) is False  # «телефона» нет в названии
    assert matches("Разработка мобильных приложений", profile)
    assert not matches("мобильная связь", profile)


def test_short_and_inflected_words() -> None:
    assert matches("игры", "разработка компьютерных игр")
    assert matches("химия", "химический инжиниринг")
    assert matches("робот", "интеллектуальные робототехнические системы")
    assert matches("программир", "информатика и программирование")
    assert matches("МАТЕМАТИК", "математика")
    assert not matches("приложения", "разработка мобильных предложений")
    assert word_matches("мобильные", "мобильных") and not word_matches("мобильные", "моб")
    assert word_matches("хим", "химический") and word_matches("биолог", "биология")


def test_service_words_are_ignored() -> None:
    assert query_words("олимпиада по программированию") == ["программированию"]
    assert query_words("для профиля биология") == ["биология"]
    assert not matches("олимпиада", "информатика")


def test_junk_and_typo_profiles() -> None:
    junk = "астрономия, Анализ данных, Естественные науки, ИБ, ИИ, Инженерное дело, Математика"
    assert is_list_profile(junk)
    legit = (
        "виртуальные миры: разработка компьютерных игр, технологии виртуальной реальности, "
        "технологии дополненной реальности, цифровые технологии в архитектуре"
    )
    assert not is_list_profile(legit)
    assert display_name("разработка мобильных предложений") == "разработка мобильных приложений"
    assert display_name("математика") == "математика"
