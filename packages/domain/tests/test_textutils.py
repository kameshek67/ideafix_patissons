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
