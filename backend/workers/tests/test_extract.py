import io
from types import SimpleNamespace

import openpyxl
from olymp_domain.extraction import ExtractionFile, quote_found
from olymp_workers.ai.tables import TableReader, page_tables
from olymp_workers.extract import adapters, cells, columns
from olymp_workers.extract.build import Adapter, extract
from olymp_workers.extract.layout import Loaded, Page, load, load_xlsx

URL = "https://example.edu/doc.pdf"
SHA = "0" * 64


def loaded_from(pages: list[tuple[str, list[list[list[str | None]]]]], url: str = URL) -> Loaded:
    """Документ из текста страниц и таблиц pdfplumber: так же, как его разбирает load_pdf."""
    reader = TableReader()
    out = []
    for number, (plain, tables) in enumerate(pages, 1):
        page = Page(number, plain)
        from olymp_workers.extract.layout import Line

        page.lines = [
            Line(i.kind, i.text, i.cells, i.code, filled=i.filled)
            for i in reader.page_items(tables)
        ]
        out.append(page)
    return Loaded(url, SHA, "pdf", out)


def run(loaded: Loaded, adapter: Adapter | None = None) -> ExtractionFile:
    result = extract(loaded, university="Вуз", campaign=2026, adapter=adapter)
    return result.file


# ---------------------------------------------------------------- ячейки


def test_programs_with_codes_names_and_exclusions() -> None:
    programs, everything = cells.parse_programs(
        "06.03.01 Биология 05.03.06 Экология и природопользование (профиль: Экология)"
    )
    assert not everything
    assert [(p.code, p.name) for p in programs] == [
        ("06.03.01", "Биология"),
        ("05.03.06", "Экология и природопользование"),
    ]
    assert programs[1].note == "(профиль: Экология)"
    codes, everything = cells.parse_programs("все, за исключением 42.03.01 45.03.02")
    assert everything and [p.code for p in codes] == ["42.03.01", "45.03.02"]


def test_profiles_split_by_semicolon_and_known_subject_commas() -> None:
    assert cells.split_profiles("астрономия; биология; робототехника, технология") == [
        "астрономия",
        "биология",
        "робототехника",
        "технология",
    ]
    # запятая внутри названия профиля не делит
    assert cells.split_profiles("виртуальные миры: разработка игр, технологии; физика") == [
        "виртуальные миры: разработка игр, технологии",
        "физика",
    ]


def test_role_levels_grades_ege() -> None:
    assert cells.parse_role("Победитель или призер") == "both"
    assert cells.parse_role("Победителям") == "winner"
    assert cells.parse_role("Призер") == "prizewinner"
    assert cells.parse_role("—") is None
    assert cells.parse_levels("1, 2 или 3") == [1, 2, 3]
    assert cells.parse_levels("I, II") == [1, 2]
    assert cells.parse_grades("10 или 11 класс") == [10, 11]
    assert cells.parse_grades("11 класс") == [11]
    assert cells.parse_subjects("Информатика и ИКТ; Английский язык, математика") == [
        "inf",
        "foreign",
        "math",
    ]
    assert cells.parse_min("75 и более") == 75
    assert cells.parse_min("ЕГЭ не ниже 80 баллов") == 80


# ---------------------------------------------------------------- колонки


def test_columns_by_header_including_reversed_text() -> None:
    assert columns.classify(
        [
            "№ п/п",
            "Название олимпиады",
            "Профиль олимпиады",
            "Профилирующий предмет",
            "Уровень олимпиады",
        ]
    ) == ["skip", "olympiad", "profile", "ege_subject", "level"]
    reversed_header = ["еинелварпаН иквотогдоп", "ыдаипмило еинавзаН", "молпиД"]
    assert columns.classify(reversed_header) == ["program", "olympiad", "role"]
    # длинная строка данных со словами из заголовка заголовком не считается
    assert not columns.looks_like_header(
        [
            "",
            "Всероссийская олимпиада школьников",
            "Промышленное программирование",
            "2",
            "Победитель",
        ]
    )


# ---------------------------------------------------------------- записи


def test_matrix_table_olympiad_and_role_from_caption() -> None:
    caption = (
        "Приложение 2.1. Соответствие профилей Всероссийской олимпиады школьников, дающих "
        "победителям и призерам право на прием без вступительных испытаний"
    )
    header = [
        "Направление",
        "Профили олимпиад",
        "Общеобразовательные предметы, подтверждающие олимпиаду",
    ]
    rows = [
        ["01.03.02 Прикладная математика", "астрономия; биология", "математика; физика"],
        ["38.03.01 Экономика", "экономика", "обществознание; математика"],
    ]
    done = run(loaded_from([(caption, [[header, *rows]])]))
    keys = [(r.program_code, r.profile) for r in done.records]
    assert keys == [
        ("01.03.02", "астрономия"),
        ("01.03.02", "биология"),
        ("38.03.01", "экономика"),
    ]
    first = done.records[0]
    assert first.benefit_type == "bvi" and first.winner_role == "both"
    assert first.olympiad == "Всероссийская олимпиада школьников"
    assert first.ege and first.ege.subjects == ["math", "phys"] and first.ege.min is None
    assert first.program_name == "Прикладная математика"


def test_row_continued_on_next_page_keeps_start_page_and_all_codes() -> None:
    caption = "Перечень олимпиад, победители и призеры которых поступают без вступительных испытаний, ЕГЭ не ниже 75 баллов"
    header = [
        "№ п/п",
        "Название олимпиады",
        "Профиль олимпиады",
        "Профилирующий предмет",
        "Уровень",
        "Направления",
    ]
    first = [
        [
            header,
            ["1", "Олимпиада «Миссия", "экономика", "обществознание", "2", "38.03.01 38.03.02"],
        ]
    ]
    second = [
        [
            ["", "выполнима»", "", "", "", "38.03.03 45.03.02"],
            ["2", "Олимпиада Б", "право", "обществознание", "3", "40.03.01"],
        ]
    ]
    done = run(loaded_from([(caption, first), ("", second)]))
    mission = [r for r in done.records if r.profile == "экономика"]
    assert [r.program_code for r in mission] == ["38.03.01", "38.03.02", "38.03.03", "45.03.02"]
    assert {r.source.page for r in mission} == {1}
    assert mission[0].olympiad == "Олимпиада «Миссия выполнима»"
    assert mission[0].ege and mission[0].ege.min == 75 and mission[0].levels == [2]
    assert [r.program_code for r in done.records if r.profile == "право"] == ["40.03.01"]


def test_empty_program_cell_inherits_previous_row_and_says_so() -> None:
    header = [
        "Направление",
        "Название олимпиады",
        "Профиль олимпиады",
        "Предмет, балл 75",
        "Уровень",
        "Диплом",
    ]
    rows = [
        ["01.03.02 Математика", "Олимпиада А", "Математика", "Математика", "1", "Победитель"],
        ["", "Олимпиада Б", "Математика", "Математика", "2", "Победитель или призер"],
    ]
    done = run(loaded_from([("Без вступительных испытаний", [[header, *rows]])]))
    second = done.records[1]
    assert second.program_code == "01.03.02" and "предыдущей" in second.note
    assert second.winner_role == "both" and second.ege and second.ege.min == 75


def test_merged_cell_without_geometry_is_not_filled_down() -> None:
    header = ["Название олимпиады", "Профиль олимпиады"]
    table = [header, ["Олимпиада А", "физика"], ["", "математика"]]
    done = run(loaded_from([("Без вступительных испытаний", [table])]))
    assert [r.profile for r in done.records] == [
        "физика"
    ]  # пустое название — не повод брать прежнее


def test_page_tables_fill_only_covered_cells() -> None:
    box = SimpleNamespace
    # колонка 0: ячейка первой строки доходит до второй, третья строка без ячейки (оборванная сетка)
    rows = [
        box(cells=[(0, 0, 10, 20), (10, 0, 20, 10)]),
        box(cells=[None, (10, 10, 20, 20)]),
        box(cells=[None, (10, 20, 20, 30)]),
    ]
    table = box(rows=rows, extract=lambda: [["А", "x"], [None, "y"], [None, "z"]])
    page = box(find_tables=lambda: [table])
    assert page_tables(page) == [[["А", "x"], [None, "y"], ["", "z"]]]


def test_msu_programs_by_name_from_kcp_pages() -> None:
    kcp = (
        "Раздел: Механико-математический факультет\n"
        '01.05.01 | Специальность "Фундаментальные математика и механика" (очная форма) | 250\n'
        "01.05.01 | в том числе по квоте | 25\n",
    )
    codes = adapters.kcp_codes(kcp)
    found = adapters.programs_by_name(codes, "cpk.msu.ru/files/kcp.pdf")(
        "Фундаментальные математика и механика"
    )
    assert [(p.code, p.name) for p in found] == [
        ("01.05.01", "Фундаментальные математика и механика")
    ]
    assert adapters.programs_by_name(codes, "x")("Неизвестное направление") == []


def test_msu_lists_of_olympiads_and_benefit_from_column() -> None:
    caption = "Особые права победителям и призерам олимпиад школьников\n* Все олимпиады школьников соответствующего уровня"
    header = [
        "Направление подготовки",
        "Перечень олимпиад",
        "Уровень олимпиад",
        "Класс, за который получен результат",
        "Победитель/ призер олимпиады",
        "Общеобразовательный предмет, по которому необходимо наличие результатов ЕГЭ не менее 75 баллов",
        "Предоставляемая льгота",
    ]
    rows = [
        [
            "Математика",
            "Олимпиада А, Олимпиада «Б, В»",
            "I",
            "11",
            "Победитель, призер",
            "Математика",
            "Зачисление без вступительных испытаний",
        ],
        [
            "Математика",
            "*",
            "II",
            "11",
            "Призер",
            "Математика",
            "Максимальное количество баллов ЕГЭ по математике",
        ],
    ]
    adapter = Adapter(
        olympiad_lists=True,
        programs=adapters.programs_by_name({"математика": "01.01.01"}, "kcp"),
    )
    done = run(loaded_from([(caption, [[header, *rows]])]), adapter)
    assert [(r.olympiad, r.benefit_type, r.winner_role) for r in done.records] == [
        ("Олимпиада А", "bvi", "both"),
        ("Олимпиада «Б, В»", "bvi", "both"),
        ("Все олимпиады школьников соответствующего уровня", "100", "prizewinner"),
    ]
    assert done.records[0].ege and done.records[0].ege.min == 75


def test_sparse_header_is_not_guessed() -> None:
    header = ["№", "", "", "Название олимпиады", "", "", "Профиль олимпиады", "", ""]
    row = ["1.", "", "", "Олимпиада А", "", "", "физика", "", ""]
    assert run(loaded_from([("Без вступительных испытаний", [[header, row]])])).records == []


def test_exclusion_list_becomes_any_program_with_note() -> None:
    header = ["Название олимпиады", "Профиль олимпиады", "Направления"]
    row = ["Олимпиада А", "физика", "все, за исключением 45.03.02"]
    done = run(loaded_from([("Без вступительных испытаний", [[header, row]])]))
    assert done.records[0].program_code == "*" and "45.03.02" in done.records[0].note


def test_quotes_are_found_on_page_text() -> None:
    header = ["Направление", "Профили олимпиад", "Предметы, подтверждающие олимпиаду"]
    row = ["01.03.02 Математика", "физика", "математика"]
    pages = [
        (
            "Профилей Всероссийской олимпиады школьников; победителям и призерам; без вступительных испытаний",
            [[header, row]],
        )
    ]
    loaded = loaded_from(pages)
    done = run(loaded)
    assert done.records and all(
        quote_found(r.source.quote, loaded.pages[r.source.page - 1].text) for r in done.records
    )


# ---------------------------------------------------------------- xlsx


def xlsx_bytes() -> bytes:
    book = openpyxl.Workbook()
    wide = book.active
    wide.title = "База"
    wide.append(
        [
            "Образовательная программа",
            "Код и наименование специальности",
            "Предмет для подтверждения",
            "Олимпиада",
            "Профиль олимпиады",
            "Уровень образования",
        ]
    )
    wide.append(
        [
            "ОП 1",
            "37.03.01 Психология",
            "Обществознание",
            "Олимпиада А",
            "право; экономика",
            "Бакалавриат",
        ]
    )
    wide.append(
        ["ОП 2", "37.03.01 Психология", "Математика", "Олимпиада А", "экономика", "Бакалавриат"]
    )
    narrow = book.create_sheet("Поиск")
    narrow.append(["Код и наименование специальности", "Олимпиада", "Профиль олимпиады"])
    narrow.append(["37.03.01 Психология", "Олимпиада А", "право"])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_xlsx_widest_sheet_rows_and_subjects_merge_inside_one_program() -> None:
    data = xlsx_bytes()
    pages = load_xlsx(data)
    assert pages[0].lines[1].row == 2
    loaded = load("https://example.edu/Олимпиады_БВИ.xlsx", data)
    assert loaded.kind == "xlsx"
    done = run(loaded)
    assert {r.source.page for r in done.records} == {1}
    assert [(r.profile, r.source.row) for r in done.records] == [
        ("право", 2),
        ("экономика", 2),
        ("экономика", 3),
    ]
    assert all(r.benefit_type == "bvi" and r.winner_role is None for r in done.records)
    assert done.records[0].ege and done.records[0].ege.subjects == ["soc"]
