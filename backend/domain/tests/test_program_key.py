"""Стабильный ключ направления: не зависит от мусора в названиях и порядка кодов."""

from olymp_domain.program_key import program_stable_key, university_key, university_of_key


def test_key_ignores_case_spaces_and_code_order() -> None:
    a = program_stable_key(
        "НИУ «Высшая школа экономики»",
        "Прикладная математика и информатика 01.03.02",
        "Профиль: Анализ данных",
    )
    b = program_stable_key(
        "НИУ  «высшая школа ЭКОНОМИКИ»",
        "прикладная  математика и информатика",
        "профиль:анализ данных",
        "01.03.02",
    )
    assert a == b
    assert university_of_key(a) == university_key("НИУ «Высшая школа экономики»")
    # коды из колонки и из названия собираются вместе и сортируются
    assert program_stable_key("Вуз", "Информатика 09.03.04", "", "09.03.01").endswith(
        "|09.03.01,09.03.04"
    )


def test_key_tells_apart_profile_and_codes() -> None:
    base = program_stable_key("Вуз", "Информатика", "Разработка игр", "09.03.04")
    assert base != program_stable_key("Вуз", "Информатика", "Анализ данных", "09.03.04")
    assert base != program_stable_key("Вуз", "Информатика", "Разработка игр", "09.03.01")
    assert base != program_stable_key("Другой вуз", "Информатика", "Разработка игр", "09.03.04")
    # название из одних кодов: ключ держится на кодах
    only_codes = program_stable_key("Вуз", "09.03.01, 09.03.04")
    assert only_codes == "вуз|||09.03.01,09.03.04"
