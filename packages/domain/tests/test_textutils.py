from olymp_domain import squash
from olymp_domain.textutils import (
    clean_text,
    extract_codes,
    find_grades,
    find_levels,
    norm_level,
    parse_enumeration,
    parse_profile_rules,
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


# строка УрФУ из листа «База» (по направлению 01.03.04), как она лежит в XLSX
URFU_RAW_RULE = (
    "Перечневые олимпиады I–III уровня, победители и призёры, дипломы 2022–2026 за 9–11 кл., "
    "профили: Астрономия (подтв.: математика, физика); Анализ данных (подтв.: информатика, "
    "математика, физика); Инженерное дело, Инженерные науки, Инженерные системы (подтв.: "
    "информатика, математика, физика); НТО (все профили) (подтв.: биология, информатика, "
    "математика, физика, химия); Робототехника (подтв.: информатика и икт, математика, физика) "
    "| ВсОШ (финал): информатика, математика, труд (технология), физика"
)


def test_urfu_confirm_subjects_are_not_profiles() -> None:
    """D1: «Астрономия (подтв.: математика, физика)» — профиль «Астрономия», а не «математика»."""
    rules = parse_profile_rules(URFU_RAW_RULE)
    by_profile = {tuple(r.profiles): r for r in rules if r.scope == "rsosh"}

    astronomy = by_profile[("Астрономия",)]
    assert astronomy.confirm == ["математика", "физика"]
    assert astronomy.levels == ["I", "II", "III"]
    assert astronomy.role == "победители и призёры"

    # скобки относятся ко всей группе через запятую
    engineering = by_profile[("Инженерное дело", "Инженерные науки", "Инженерные системы")]
    assert engineering.confirm == ["информатика", "математика", "физика"]

    robotics = by_profile[("Робототехника",)]
    assert robotics.confirm == ["информатика и икт", "математика", "физика"]
    # хвост после «|» — отдельное правило ВсОШ, оно не портит область предыдущего
    assert robotics.scope == "rsosh"

    # ни один предмет подтверждения не стал профилем
    all_profiles = {p for r in rules for p in r.profiles if r.scope == "rsosh"}
    assert not all_profiles & {"математика", "физика", "информатика", "биология", "химия"}


def test_urfu_nto_all_profiles_is_a_whole_olympiad() -> None:
    """D1: «НТО (все профили)» — вся олимпиада НТО, а не профиль «все профили»."""
    rules = parse_profile_rules(URFU_RAW_RULE)
    nto = [r for r in rules if r.whole_olympiads]
    assert len(nto) == 1
    assert nto[0].whole_olympiads == ["НТО"]
    assert nto[0].profiles == []
    assert nto[0].confirm == ["биология", "информатика", "математика", "физика", "химия"]
    assert not any("все профили" in p for r in rules for p in r.profiles)


def test_urfu_detailed_rule_without_confirm_keeps_nto() -> None:
    """Лист «УрФУ подробно» (без «подтв.»): НТО в общем списке не теряет остальные профили."""
    text = (
        "Перечневые олимпиады I–III уровня по профилям: Астрономия, Анализ данных, Математика, "
        "НТО (все профили), Программирование, Физика"
    )
    rules = parse_profile_rules(text)
    assert [r.whole_olympiads for r in rules] == [["НТО"]]
    assert rules[0].profiles == [
        "Астрономия",
        "Анализ данных",
        "Математика",
        "Программирование",
        "Физика",
    ]
    assert rules[0].confirm == []


def test_profile_list_in_brackets_still_works() -> None:
    """Перечисление профилей в скобках (ИТМО) разбирается как раньше."""
    text = (
        "все технологические профили (мобильные приложения, большие данные, "
        "искусственный интеллект) — БВИ"
    )
    rules = parse_profile_rules(text)
    assert rules and rules[0].confirm == [] and rules[0].whole_olympiads == []
    assert "мобильные приложения" in rules[0].profiles
