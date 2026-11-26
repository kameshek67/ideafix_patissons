import pytest
from olymp_domain.verify import (
    CONFIRMED,
    CONTRADICTED,
    NOT_FOUND,
    UNVERIFIED,
    Answer,
    AnswerError,
    Mismatch,
    Page,
    RowKeys,
    clean_program_name,
    normalize,
    parse_answer,
    phrase_pattern,
    quote_on_page,
    reconcile,
    score_page,
    select_pages,
)

PAGE = (
    "Приложение 2. Особые права\n"
    "01.03.02 Прикладная математика и информатика\n"
    "Победителям и призёрам Московской олимпиады школь-\n"
    "ников по информатике (уровень I) — право на приём без\n"
    "вступительных испытаний. Подтверждение: ЕГЭ по информатике не ниже 75 баллов."
)
KEYS = RowKeys(
    olympiad_names=("Московская олимпиада школьников", "МОШ"),
    profile="информатика",
    program_code="01.03.02",
    program_name="Прикладная математика и информатика",
)


def test_normalize_ignores_layout() -> None:
    assert normalize("«Высшая  проба» —\nпро-\nграмма, ЁЛКА") == "высшаяпробапрограммаелка"


def test_quote_found_despite_hyphenation_and_case() -> None:
    assert quote_on_page("Московской олимпиады школьников по информатике (уровень I)", PAGE)


@pytest.mark.parametrize(
    "quote",
    [
        "Московской олимпиады",  # слишком коротко
        "Победителям Всесибирской олимпиады по информатике",  # такого нет
        "Подтверждение: ЕГЭ по информатике не ниже 80 баллов",  # число изменено
    ],
)
def test_quote_rejected(quote: str) -> None:
    assert not quote_on_page(quote, PAGE)


def test_inflected_name_is_found() -> None:
    pattern = phrase_pattern("Московская олимпиада школьников")
    assert pattern is not None
    assert pattern.search("победителям московской олимпиады школьников")


def test_short_name_only_as_word() -> None:
    pattern = phrase_pattern("НТО")
    assert pattern is not None
    assert pattern.search("олимпиада нто, профиль")
    assert not pattern.search("он то пришёл, но ничего")
    assert not pattern.search("антонов")


def test_too_generic_name_is_ignored() -> None:
    assert phrase_pattern("ОШ") is None


def test_score_requires_olympiad() -> None:
    assert score_page(KEYS, "01.03.02 Прикладная математика и информатика") == 0
    assert score_page(KEYS, PAGE) == 3 + 3 + 3 + 2


def test_code_not_matched_inside_longer_code() -> None:
    keys = RowKeys(("МОШ",), program_code="01.03.02")
    assert score_page(keys, "МОШ 101.03.02") == 3
    assert score_page(keys, "МОШ 01.03.021") == 3


def test_select_pages_orders_and_labels() -> None:
    pages = [
        Page("u", 1, "Общие положения"),
        Page("u", 2, "МОШ без кода направления"),
        Page("u", 3, PAGE),
    ]
    picked = select_pages(KEYS, pages)
    assert [(p.number, p.label) for p in picked] == [(3, "P1"), (2, "P2")]
    assert select_pages(KEYS, [pages[0]]) == []


def test_long_page_is_cut_around_olympiad() -> None:
    long_text = "а " * 20_000 + PAGE + " б" * 20_000
    picked = select_pages(KEYS, [Page("u", 7, long_text)], max_chars=3000)
    assert len(picked[0].text) == 3000
    assert "Московской" in picked[0].text


def test_parse_answer_from_fenced_json() -> None:
    answer = parse_answer(
        'Вот ответ:\n```json\n{"verdict": "confirmed", "page": "p1", "quote": "q", '
        '"mismatches": [], "comment": "ок"}\n```'
    )
    assert answer == Answer(CONFIRMED, "P1", "q", (), "ок")


@pytest.mark.parametrize(
    "text",
    [
        "не знаю",
        '{"verdict": "maybe"}',
        '{"verdict": "confirmed", "page": 1}',
        '{"verdict": "contradicted", "mismatches": [{"field": "price", "document": "x"}]}',
        '{"verdict": "confirmed", "quote": 5}',
        '["confirmed"]',
        '{"verdict": "confirmed",',
    ],
)
def test_parse_answer_rejects(text: str) -> None:
    with pytest.raises(AnswerError):
        parse_answer(text)


PAGES = [Page("u", 3, PAGE, "P1")]
QUOTE = "Победителям и призёрам Московской олимпиады школьников по информатике"


def test_confirmed_with_real_quote() -> None:
    verdict = reconcile(Answer(CONFIRMED, "P1", QUOTE, (), ""), PAGES)
    assert verdict.status == CONFIRMED
    assert verdict.page is not None and verdict.page.number == 3


def test_invented_quote_is_unverified() -> None:
    answer = Answer(
        CONFIRMED, "P1", "Победителям олимпиады ИТМО даётся БВИ на все направления", (), ""
    )
    assert reconcile(answer, PAGES).status == UNVERIFIED


def test_unknown_page_is_unverified() -> None:
    assert reconcile(Answer(CONFIRMED, "P7", QUOTE, (), ""), PAGES).status == UNVERIFIED


def test_confirmed_with_mismatch_becomes_contradicted() -> None:
    mismatch = (Mismatch("min_ege", "75"),)
    verdict = reconcile(Answer(CONFIRMED, "P1", QUOTE, mismatch, ""), PAGES)
    assert verdict.status == CONTRADICTED
    assert verdict.mismatches == mismatch


def test_not_found_needs_no_quote() -> None:
    assert reconcile(Answer(NOT_FOUND, None, "", (), "нет"), PAGES).status == NOT_FOUND


def test_program_name_without_number_and_code() -> None:
    assert clean_program_name("№15. Программная инженерия (09.03.04)") == "Программная инженерия"
    assert clean_program_name("01.03.02 Прикладная математика") == "Прикладная математика"


def test_numbered_program_name_still_matches() -> None:
    keys = RowKeys(("МОШ",), program_name="№15. Программная инженерия (09.03.04)")
    assert score_page(keys, "МОШ. Программной инженерии — БВИ") == 3 + 3


def test_excerpt_prefers_mention_with_details() -> None:
    keys = RowKeys(("МОШ",), profile="история", program_code="38.03.05")
    filler = "строка про другое " * 300
    text = "МОШ физика 01.03.02. " + filler + "МОШ история 38.03.05 БВИ. " + filler
    picked = select_pages(keys, [Page("u", 1, text)], max_chars=2000)[0].text
    assert "история 38.03.05" in picked


def test_quote_must_mention_olympiad_when_keys_given() -> None:
    other = "Подтверждение: ЕГЭ по информатике не ниже 75 баллов"
    assert reconcile(Answer(CONFIRMED, "P1", other, (), ""), PAGES).status == CONFIRMED
    verdict = reconcile(Answer(CONFIRMED, "P1", other, (), ""), PAGES, KEYS)
    assert verdict.status == UNVERIFIED
    assert reconcile(Answer(CONFIRMED, "P1", QUOTE, (), ""), PAGES, KEYS).status == CONFIRMED


def test_bare_olympiad_name_is_not_evidence() -> None:
    page = [Page("u", 1, "Московская олимпиада школьников\nПобедителям — БВИ по информатике", "P1")]
    bare = Answer(CONFIRMED, "P1", "Московская олимпиада школьников", (), "")
    full = Answer(CONFIRMED, "P1", "Московская олимпиада школьников Победителям — БВИ", (), "")
    verdict = reconcile(bare, page, KEYS)
    assert verdict.status == UNVERIFIED
    assert "только название" in verdict.comment
    assert reconcile(full, page, KEYS).status == CONFIRMED
