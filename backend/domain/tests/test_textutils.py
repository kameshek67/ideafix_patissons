from olymp_domain import squash
from olymp_domain.textutils import (
    clean_text,
    extract_codes,
    find_ege_thresholds,
    find_grades,
    find_levels,
    find_roles,
    find_subjects,
    has_profile_rule,
    norm_level,
    norm_role,
    parse_enumeration,
    parse_profile_rules,
    profile_stems,
    split_sentences,
    split_source,
    split_top_level,
    vsosh_subjects,
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


def test_vsosh_rule_by_subjects() -> None:
    (rule,) = parse_profile_rules(
        "ВсОШ (финал): информатика, математика, труд (технология), физика"
    )
    assert rule.scope == "vsosh"
    assert rule.profiles == ["информатика", "математика", "труд", "физика"]
    (rule,) = parse_profile_rules("ВсОШ (финал, 9–11 кл.): математика, информатика, физика")
    assert rule.profiles == ["математика", "информатика", "физика"]


def test_vsosh_rule_skips_scholarships_and_general_phrases() -> None:
    # стипендия — не льгота при приёме; «по профилю» без предметов — не правило по предметам
    assert not parse_profile_rules("Стипендия 50 000 ₽ — победителям и призёрам ВсОШ по физике")
    assert not parse_profile_rules(
        "ВсОШ (финал) и сборные — БВИ по направлениям, соответствующим профилю"
    )


def test_find_levels_keeps_only_recognized_levels() -> None:
    assert find_levels("олимпиада I уровня, олимпиада II уровня") == ["I", "II"]
    assert find_levels("ур. 3") == ["III"]
    assert find_levels("перечневые олимпиады без указания уровня") == []


def test_find_roles_distinguishes_only_winners() -> None:
    assert find_roles("только победители и призёры олимпиады") == [
        "только победители",
        "призёры",
    ]
    assert find_roles("победители и призёры олимпиад перечня") == ["победители", "призёры"]
    assert find_roles("призёры ВсОШ") == ["призёры"]


def test_norm_role_abbreviations() -> None:
    assert norm_role("поб.+приз.") == "победители и призёры"
    assert norm_role("только поб.") == "только победители"
    assert norm_role("призёры") == "призёры"
    assert norm_role("олимпиада перечня") == "олимпиада перечня"


def test_find_grades_returns_first_grade_of_range() -> None:
    assert find_grades("для 9–11 кл.") == ["9"]
    assert find_grades("обучающимся 10, 11 классов") == ["10"]
    assert find_grades("11 класс") == ["11"]


def test_find_ege_thresholds_reads_minimum_scores() -> None:
    assert find_ege_thresholds("не ниже 75 баллов") == ["75"]
    assert find_ege_thresholds("≥ 82 балла") == ["82"]
    assert find_ege_thresholds("не ниже 80 баллов ЕГЭ, ≥ 70 баллов") == ["80", "70"]
    assert find_ege_thresholds("109 баллов") == []


def test_find_subjects_matches_exact_forms_in_subjects_list() -> None:
    assert find_subjects("ЕГЭ: математика, физика, информатика") == [
        "математика",
        "информатика",
        "физика",
    ]
    assert find_subjects("подтверждение: русский язык, математика") == [
        "математика",
        "русский язык",
    ]
    assert find_subjects("ЕГЭ по математике и физике") == []


def test_split_top_level_ignores_separators_in_brackets_and_quotes() -> None:
    assert split_top_level("«Высшая проба (открытая)» — I ур.; «Ломоносов» — II ур.") == [
        "«Высшая проба (открытая)» — I ур",
        "«Ломоносов» — II ур",
    ]
    assert split_top_level("«математика; физика»; информатика") == [
        "«математика; физика»",
        "информатика",
    ]
    assert split_top_level("Астрономия (подтв.: математика, физика); Анализ данных", ",;") == [
        "Астрономия (подтв.: математика, физика)",
        "Анализ данных",
    ]


def test_split_sentences_keeps_abbreviations_and_breaks_on_capital() -> None:
    assert split_sentences("Побед. и призёры БВИ. ВсОШ (финал): математика.") == [
        "Побед. и призёры БВИ",
        "ВсОШ (финал): математика",
    ]
    assert split_sentences("Московская олимпиада — победители; ВсОШ — призёры. НТО — I ур.") == [
        "Московская олимпиада — победители",
        "ВсОШ — призёры",
        "НТО — I ур",
    ]


def test_vsosh_subjects_extracts_subjects_and_skips_scholarships() -> None:
    assert vsosh_subjects("ВсОШ (финал): математика, информатика, труд (технология), физика") == [
        "математика",
        "информатика",
        "труд",
        "физика",
    ]
    assert vsosh_subjects("победителям ВсОШ по информатике и математике — БВИ") == [
        "информатике",
        "математике",
    ]
    assert vsosh_subjects("Стипендия 50 000 ₽ — победителям ВсОШ по физике") == []


def test_has_profile_rule_detects_list_rules() -> None:
    assert has_profile_rule("Любая олимпиада перечня по профилю ИКТ")
    assert has_profile_rule("Перечневые олимпиады I–III уровня")
    assert has_profile_rule("все технологические профили — БВИ")
    assert not has_profile_rule("«Высшая проба» (информатика, I ур.)")


def test_parse_profile_rules_various_wording() -> None:
    (rule,) = parse_profile_rules(
        "любая олимпиада перечня I–III уровня по профилям: математика, физика, информатика "
        "— побед. и призёры"
    )
    assert rule.scope == "rsosh"
    assert rule.profiles == ["математика", "физика", "информатика"]
    assert rule.levels == ["I", "II", "III"]
    assert rule.role == "победители и призёры"

    (rule,) = parse_profile_rules(
        "Любая олимпиада перечня: Астрономия (подтв.: математика, физика) — победители и призёры"
    )
    assert rule.profiles == ["Астрономия"]
    assert rule.confirm == ["математика", "физика"]
    assert rule.levels == []

    (rule,) = parse_profile_rules("ВсОШ (финал, 9–11 кл.): математика, физика — БВИ")
    assert rule.scope == "vsosh"
    assert rule.profiles == ["математика", "физика"]
    assert rule.role == ""


def test_profile_stems_uses_first_six_letters_sorted() -> None:
    assert profile_stems("Информатика") == ("информ",)
    assert profile_stems("Математическое моделирование и искусственный интеллект") == (
        "интелл",
        "искусс",
        "матема",
        "модели",
    )
    assert profile_stems("ИКТ (информационные и коммуникационные технологии)") == (
        "икт",
        "информ",
        "коммун",
        "технол",
    )


def test_extract_codes_from_admission_directions() -> None:
    assert extract_codes("Направления 01.03.02, 09.03.01 и 02.03.01") == [
        "01.03.02",
        "09.03.01",
        "02.03.01",
    ]
    assert extract_codes("код 01.03.02. Прикладная математика") == ["01.03.02"]
    assert extract_codes("направление 1.03.02") == []


def test_split_source_without_and_with_url() -> None:
    assert split_source("Приказ № 45") == ("Приказ № 45", "")
    title, url = split_source(
        "Приложение 2 «Особые права» — https://ba.hse.ru/mirror/pubs/share/1170753560"
    )
    assert title == "Приложение 2 «Особые права»"
    assert url == "https://ba.hse.ru/mirror/pubs/share/1170753560"
    title, url = split_source("Правила приёма: https://example.ru/Приказ 2026.pdf")
    assert title == "Правила приёма: 2026.pdf"
    assert url == "https://example.ru/%D0%9F%D1%80%D0%B8%D0%BA%D0%B0%D0%B7"
