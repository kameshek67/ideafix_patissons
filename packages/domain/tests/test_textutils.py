from olymp_domain import squash
from olymp_domain.textutils import (
    clean_text,
    extract_codes,
    find_grades,
    find_levels,
    norm_level,
    parse_enumeration,
    split_source,
)


def test_squash_ignores_noise() -> None:
    # артефакты извлечения из PDF: цифры внутри слов, кавычки, ё
    assert squash("Всероссийская о4л импиада") == squash("всероссийская олимпиада")
    assert squash("«Покори Воробьёвы горы!»") == "покориворобьевыгоры"


def test_clean_text_collapses_whitespace() -> None:
    assert clean_text("  Высшая   проба \n") == "Высшая проба"
    assert clean_text(None) == ""


def test_extract_codes() -> None:
    assert extract_codes("№3. Прикладная математика и информатика (01.03.02)") == ["01.03.02"]


def test_levels_and_grades() -> None:
    assert norm_level("II") == "II"
    assert "I" in find_levels("олимпиады I уровня")
    assert find_grades("для 10, 11 класса")


def test_split_source_separates_title_and_url() -> None:
    title, url = split_source("Приложение 2 — https://ba.hse.ru/mirror/pubs/share/1170753560")
    assert url == "https://ba.hse.ru/mirror/pubs/share/1170753560"
    assert title.startswith("Приложение 2")


def test_parse_enumeration_formats() -> None:
    items = parse_enumeration(
        "«Высшая проба» (информатика, I ур.); «Ломоносов» (математика, I ур.)"
    )
    names = [i.name for i in items]
    assert any("Высшая проба" in n for n in names)
    assert any("Ломоносов" in n for n in names)
    assert all(i.level == "I" for i in items)


ITMO_SUBJECT_LISTS = (
    "САМОЕ ЖЁСТКОЕ направление ИТМО — только поимённый список олимпиад. Информатика: Высшая проба, "
    "Московская, СПбГУ, Олимпиада по информатике и программированию (ИТМО), Открытая олимпиада по "
    "программированию, Вузовско-академическая — I ур., побед. и призёры; Всесибирская, Innopolis Open — "
    "побед. и призёры; Ломоносов — только победители; ТехноКубок, Когнитивные технологии, Открытая "
    "олимпиада школьников — только победители; НТО «Большие данные» — победители. Математика: Высшая "
    "проба, Московская, СПбГУ, Санкт-Петербургская, Турнир городов, Турнир Ломоносова, ЮМШ — побед. и "
    "призёры; Ломоносов, ПВГ, Всесибирская, ведомственная, ОММО, Формула Единства, Курчатов, Физтех, "
    "Открытая — только победители. ИИ (Всерос. олимпиада по ИИ) — победители"
)


def test_itmo_subject_lists_keep_every_olympiad_with_its_role():
    """ИТМО 01.03.02: «побед. и призёры» не превращается в «победители», олимпиады не теряются."""
    from olymp_domain.textutils import parse_enumeration

    rows = parse_enumeration(ITMO_SUBJECT_LISTS)
    assert len(rows) == 30
    by = {(r.name, r.profile): r for r in rows}
    assert by[("Высшая проба", "информатика")].role == "победители и призёры"
    assert by[("Высшая проба", "информатика")].level == "I"
    assert by[("Ломоносов", "информатика")].role == "только победители"
    assert by[("НТО «Большие данные»", "информатика")].role == "победители"
    # олимпиады, которые общий разбор терял
    for name in ("ПВГ", "ЮМШ", "ТехноКубок", "Московская", "Курчатов", "Физтех"):
        assert any(r.name == name for r in rows), name
    assert by[("ЮМШ", "математика")].role == "победители и призёры"
    assert by[("ПВГ", "математика")].role == "только победители"
    assert by[("Всерос. олимпиада по ИИ", "ии")].role == "победители"
    # в имя не попадает заголовок «САМОЕ ЖЁСТКОЕ направление ИТМО»
    assert not any("ЖЁСТКОЕ" in r.name for r in rows)


def test_other_enumerations_are_not_affected_by_subject_lists_parser():
    from olymp_domain.textutils import parse_enumeration

    rows = parse_enumeration("«Высшая проба» (информатика, I ур.); «Ломоносов» (математика, I ур.)")
    assert [(r.name, r.profile, r.level) for r in rows] == [
        ("«Высшая проба»", "информатика", "I"),
        ("«Ломоносов»", "математика", "I"),
    ]
