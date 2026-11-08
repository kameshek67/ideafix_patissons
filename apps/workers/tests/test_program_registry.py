"""Сопоставление программ вуза между листами XLSX (D2): код не склеивает разные программы."""

from olymp_workers.ingest import ProgramRegistry, program_keys


class _Cursor:
    def __init__(self, value: int) -> None:
        self._value = value

    def fetchone(self) -> tuple[int]:
        return (self._value,)


class _FakeConn:
    """Достаточно для ProgramRegistry: INSERT … RETURNING id и UPDATE."""

    def __init__(self) -> None:
        self.last_id = 0

    def execute(self, sql: str, params: tuple = ()) -> _Cursor:
        if sql.lstrip().startswith("INSERT"):
            self.last_id += 1
        return _Cursor(self.last_id)


def _registry() -> ProgramRegistry:
    return ProgramRegistry(_FakeConn())  # type: ignore[arg-type]


def test_list_number_and_direction_suffix_do_not_hide_the_name() -> None:
    keys = program_keys("№24. Экономика (38.03.01)", "38.03.01")
    detail = program_keys("Экономика", "38.03.01")
    assert {"nc:экономика|38.03.01", "c:38.03.01"} <= set(keys) & set(detail)
    # «Игры (по направлению 09.03.04 …)» узнаётся по названию до скобки
    assert "nc:разработкаигрицифровыхпродуктов|09.03.04" in program_keys(
        "Разработка игр и цифровых продуктов (по направлению 09.03.04 Программная инженерия)"
    )


def test_base_rows_with_same_code_stay_separate_programs() -> None:
    reg = _registry()
    a = reg.get_or_create(
        1, "№3. Прикладная математика и информатика (01.03.02)", match_by_code=False
    )
    b = reg.get_or_create(1, "№4. Прикладной анализ данных (01.03.02)", match_by_code=False)
    assert a != b


def test_detail_row_finds_program_by_name_even_when_code_is_shared() -> None:
    reg = _registry()
    a = reg.get_or_create(
        1, "№3. Прикладная математика и информатика (01.03.02)", match_by_code=False
    )
    b = reg.get_or_create(1, "№4. Прикладной анализ данных (01.03.02)", match_by_code=False)
    assert reg.get_or_create(1, "Прикладная математика и информатика", code="01.03.02") == a
    assert reg.get_or_create(1, "Прикладной анализ данных", code="01.03.02") == b


def test_code_alone_matches_only_when_it_is_unambiguous() -> None:
    reg = _registry()
    only = reg.get_or_create(1, "Программная инженерия (09.03.04)", match_by_code=False)
    # единственная программа с этим кодом: подробный лист называет её просто кодом (МИФИ)
    assert reg.get_or_create(1, "09.03.04", code="09.03.04") == only

    first = reg.get_or_create(1, "Математика (01.03.01)", match_by_code=False)
    reg.get_or_create(1, "Математика и физика (01.03.01)", match_by_code=False)
    # два программы с кодом 01.03.01 — по одному коду не определить, какая из них
    new = reg.get_or_create(1, "01.03.01", code="01.03.01")
    assert new != first
    # у другого вуза тот же код — другая программа
    assert reg.get_or_create(2, "Математика (01.03.01)", match_by_code=False) not in (first, new)


def test_same_name_with_different_codes_is_not_merged() -> None:
    """ВШЭ: «Разработка игр и цифровых продуктов» есть и на 09.03.04, и на 54.03.01."""
    reg = _registry()
    it = reg.get_or_create(
        1, "№17. Разработка игр и цифровых продуктов (09.03.04)", match_by_code=False
    )
    design = reg.get_or_create(
        1, "№63. Разработка игр и цифровых продуктов (54.03.01)", match_by_code=False
    )
    assert it != design
    assert reg.get_or_create(1, "Разработка игр и цифровых продуктов", code="54.03.01") == design
    assert reg.get_or_create(1, "Разработка игр и цифровых продуктов", code="09.03.04") == it


def test_truncated_detail_name_finds_its_program_only_when_unambiguous() -> None:
    """КФУ: в подробном листе длинное название обрезано."""
    reg = _registry()
    base = "44.03.05 Педагогическое образование (с двумя профилями подготовки) (профиль: "
    a = reg.get_or_create(
        1, base + "Русский язык и иностранный (английский) язык)", match_by_code=False
    )
    b = reg.get_or_create(1, base + "Русский язык и литература)", match_by_code=False)
    c = reg.get_or_create(1, base + "Русский язык и литература, второй язык)", match_by_code=False)
    cut = base + "Русский язык и иностранный (английский) я"
    assert reg.get_or_create(1, cut, code="44.03.05") == a
    # обрезок, подходящий двум программам, не приписываем ни одной из них
    ambiguous = reg.get_or_create(1, base + "Русский язык и лите", code="44.03.05")
    assert ambiguous not in (a, b, c)
