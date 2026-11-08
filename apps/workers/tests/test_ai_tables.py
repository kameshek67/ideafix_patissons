from olymp_workers.ai.tables import TABLES_TITLE, TableReader, page_text

HEADER = [
    "№ п/п",
    "Наименование образовательной программы",
    "Полное наименование олимпиады из Перечня олимпиад школьников***",
    "Профиль олимпиады",
    "Вид особого права",
]
PAGE_1 = [
    [
        HEADER,
        ["Направление подготовки 09.03.04 Программная инженерия", None, None, None, None],
        [None, None, "Олимпиада «Росатом»", "физика", "Право на прием БВИ"],
        [None, None, None, None, "Право на 100 баллов"],
    ]
]
PAGE_2 = [  # на следующей странице нет колонок «№» и «программа»
    [
        [None, "физика", "Право на 100 баллов\nпризерам"],
        ["Олимпиада «Физтех»", "математика", "Право на прием БВИ"],
        ["Направление подготовки 01.03.02 Прикладная математика", None, None],
        [None, "информатика", "Право на прием БВИ"],
    ]
]


def test_merged_cells_are_filled_and_sections_prefix_rows() -> None:
    reader = TableReader()
    first = reader.page_lines(PAGE_1)
    assert first[0].startswith("Колонки: № п/п | Наименование образовательной программы |")
    assert first[1] == "Раздел: Направление подготовки 09.03.04 Программная инженерия"
    assert first[2] == "[09.03.04]  |  | Олимпиада «Росатом» | физика | Право на прием БВИ"
    assert first[3] == "[09.03.04]  |  | Олимпиада «Росатом» | физика | Право на 100 баллов"


def test_table_continues_on_next_page() -> None:
    reader = TableReader()
    reader.page_lines(PAGE_1)
    second = reader.page_lines(PAGE_2)
    # заголовок выровнен по правому краю под три колонки
    assert (
        second[0]
        == "Колонки: Полное наименование олимпиады из Перечня… | Профиль олимпиады | Вид особого права"
    )
    # первая строка страницы: олимпиады нет в этой таблице, раздел перешёл со страницы 1
    assert second[1] == "[09.03.04]  | физика | Право на 100 баллов призерам"
    assert second[2] == "[09.03.04] Олимпиада «Физтех» | математика | Право на прием БВИ"
    assert second[3] == "Раздел: Направление подготовки 01.03.02 Прикладная математика"
    assert second[4] == "[01.03.02] Олимпиада «Физтех» | информатика | Право на прием БВИ"


def test_empty_cells_are_not_filled() -> None:
    reader = TableReader()
    lines = reader.page_lines([[["МОШ", "физика", "БВИ"], ["ПВГ", "", "100 баллов"]]])
    assert lines[1] == "ПВГ |  | 100 баллов"


def test_page_text_puts_tables_first() -> None:
    assert page_text("текст", []) == "текст"
    text = page_text("текст", ["строка"])
    assert text.startswith(TABLES_TITLE)
    assert text.index("строка") < text.index("текст")


def test_continuation_row_with_one_cell_is_data() -> None:
    reader = TableReader()
    lines = reader.page_lines(
        [
            [
                ["Раздел 38.03.01 Экономика", None, None],
                ["МОШ", "физика", "БВИ"],
                [None, None, "100 баллов"],
            ]
        ]
    )
    assert lines == [
        "Раздел: Раздел 38.03.01 Экономика",
        "[38.03.01] МОШ | физика | БВИ",
        "[38.03.01] МОШ | физика | 100 баллов",
    ]
