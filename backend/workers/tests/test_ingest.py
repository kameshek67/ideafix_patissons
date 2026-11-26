"""Сборка базы из настоящего XLSX: числа совпадают со сборкой прототипа (ветка main)."""

import json
from pathlib import Path

import psycopg
import pytest
from olymp_db.session import psycopg_dsn
from olymp_domain.olympiad_cards import CardError
from olymp_workers.olympiad_cards import CARDS_FILE, load_olympiad_cards

# Итог сборки. Исходно совпадал со сборкой прототипа на SQLite по тому же файлу
# data/Olimpiady_BVI_100ballov.xlsx (programs 710, benefits 53286, derived 26288, profiles 638);
# изменён осознанно (план качества помощника, D1 и D2):
#  - D2: программы с одним кодом больше не склеиваются по коду (ВШЭ, КФУ, филиалы ВШЭ) -> +51 программа;
#  - D1: правила УрФУ разбираются как «профиль (подтв.: предметы)», НТО УрФУ раскрывается целиком;
#  - B8: льготы ВсОШ и международных олимпиад больше не теряются: правила «ВсОШ по предметам»
#    раскрываются в строки (+235: Горный, Иннополис, ЦУ, МГЮА, НГУ и др.), общее правило КФУ
#    «олимпиады всех уровней — на направления по профилю» даёт ВсОШ по предметам ВИ (+206),
#    льгота сборным из «ВШЭ международные» раскрыта по программам (+174), IMO, OWAO и IJSO больше
#    не приклеиваются к «Формуле Единства», СПб астрономической и «Юниору» (олимпиад 173 -> 176);
#  - B12b: слой document — льготы из data/extracted поверх XLSX: +5657 строк (ВШЭ 116, ИТМО 49, КФУ 252,
#    МАИ 1378, МЭИ 400, МГУ 259, РАНХиГС 3203), заменено 164 строки XLSX (ВШЭ 84, ИТМО 33, КФУ 47),
#    +123 направления вузов, у которых не было направления с таким кодом (МАИ, МЭИ, МГУ, РАНХиГС, КФУ);
#  - C1: разбор условий — диапазоны классов («9–11 кл.»), падежи предметов («по математике»), роль «только
#    победители» -> «победители»: ключевых слов 137963 -> 142261 (классов 8510 -> 11376).
#  - C3: записи документов «все олимпиады перечня» раскрываются по профилю в пары «олимпиада + профиль»
#    РСОШ (слой derived): +976 строк (ИТМО 27, МГУ 949), documents_added 5657 -> 6633.
EXPECTED = {
    "universities": "39",
    "programs": "833",
    "benefits": "60196",
    "benefits_bvi": "36374",
    "benefits_sto": "23018",
    "benefits_raw": "859",
    "benefits_rows": "59719",
    "benefits_derived": "27654",
    "benefits_notes": "477",
    "olympiads": "176",
    "profiles": "658",
    "links": "69854",
    "keywords": "142261",
    "fts": "on",
    "documents_added": "6633",
    "documents_replaced": "164",
}


def test_totals_match_prototype(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    assert {k: meta.get(k) for k in EXPECTED} == EXPECTED
    assert meta["source_file"] == "Olimpiady_BVI_100ballov.xlsx"


def test_no_dangling_links(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        dangling = conn.execute(
            """SELECT COUNT(*) FROM benefit_olympiads bo
               LEFT JOIN olympiad_profiles p ON p.id = bo.profile_id
               WHERE bo.profile_id IS NOT NULL AND p.id IS NULL"""
        ).fetchone()
    assert dangling == (0,)


def test_every_program_has_source(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        missing = conn.execute("SELECT COUNT(*) FROM programs WHERE source_url = ''").fetchone()
        pages = conn.execute("SELECT COUNT(*) FROM universities WHERE docs_url = ''").fetchone()
    assert missing == (0,)
    assert pages == (0,)


def test_search_index_covers_non_derived_rows(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        indexed, expected = conn.execute(
            """SELECT (SELECT COUNT(*) FROM search_index),
                      (SELECT COUNT(*) FROM benefits WHERE layer <> 'derived')"""
        ).fetchone()
        hits = conn.execute(
            "SELECT COUNT(*) FROM search_index WHERE document @@ to_tsquery('simple', 'физтех:*')"
        ).fetchone()
    assert indexed == expected
    assert hits[0] > 0


def test_benefit_ids_follow_build_order(built_database_url: str) -> None:
    """id льгот выдаёт сборка: последовательность должна быть сдвинута за последний id."""
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        max_id = conn.execute("SELECT MAX(id) FROM benefits").fetchone()[0]
        next_id = conn.execute(
            "SELECT nextval(pg_get_serial_sequence('benefits', 'id'))"
        ).fetchone()[0]
    assert next_id == max_id + 1


def test_extra_points_loaded_with_sources(built_database_url: str) -> None:
    """Баллы за ИД: строки загружены, у каждой есть источник, вузы из справочника."""
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        no_source = conn.execute(
            "SELECT COUNT(*) FROM individual_achievements"
            " WHERE source_url NOT LIKE 'https://%' OR source_quote = '' OR source_page IS NULL"
        ).fetchone()[0]
    # T-084: к 7 вузам T-051 добавлены правила ещё 19 записей вузов (Бауманка — вместе с филиалами)
    assert (meta["extra_rules"], meta["extra_universities"], meta["extra_limits"]) == (
        "999",
        "26",
        "24",
    )
    assert no_source == 0


def test_extra_points_reload_is_idempotent_and_keeps_data_on_error(
    built_database_url: str, tmp_path
) -> None:
    """Перезагрузка баллов при выкате: тот же результат, а ошибка в CSV не стирает данные."""
    import shutil
    from pathlib import Path

    import pytest
    from olymp_workers.extra_points import ExtraPointsDataError, reload_extra_points

    data = Path(__file__).resolve().parents[3] / "data"

    def counts() -> tuple[int, int, str]:
        with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
            rules = conn.execute("SELECT COUNT(*) FROM individual_achievements").fetchone()[0]
            limits = conn.execute("SELECT COUNT(*) FROM individual_achievement_limits").fetchone()[
                0
            ]
            version = conn.execute(
                "SELECT value FROM meta WHERE key = 'extra_points_version'"
            ).fetchone()[0]
        return rules, limits, version

    before = counts()
    assert reload_extra_points(built_database_url, data) == {"rules": 999, "limits": 24}
    assert counts() == before

    broken = tmp_path / "data"
    shutil.copytree(data, broken, ignore=shutil.ignore_patterns("*.xlsx"))
    text = (broken / "individual_achievements.csv").read_text(encoding="utf-8")
    (broken / "individual_achievements.csv").write_text(
        text.replace("Университет ИТМО", "Несуществующий вуз", 1), encoding="utf-8"
    )
    with pytest.raises(ExtraPointsDataError):
        reload_extra_points(built_database_url, broken)
    assert counts() == before


def test_itmo_01_03_02_keeps_roles_and_short_named_olympiads(built_database_url: str) -> None:
    """T-067: «побед. и призёры» не превращается в «победители», МОШ, ПВГ, НТО и ЮМШ не теряются."""
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        rows = conn.execute(
            """SELECT o.short_name, b.olympiad_profile, b.winner_role
               FROM benefits b
               JOIN programs p ON p.id = b.program_id
               JOIN universities u ON u.id = p.university_id
               JOIN benefit_olympiads bo ON bo.benefit_id = b.id
               JOIN olympiads o ON o.id = bo.olympiad_id
               WHERE u.short_name = 'Университет ИТМО' AND p.code LIKE '%01.03.02%'
                 AND b.layer IN ('detailed', 'derived', 'document')"""
        ).fetchall()
    # строки документа пишут профиль с заглавной буквы
    got = {(o, p.lower(), role) for o, p, role in rows}
    assert ("«Высшая проба»", "информатика", "победители и призёры") in got
    assert ("«Высшая проба»", "математика", "победители и призёры") in got
    assert not any(r[0] == "«Высшая проба»" and r[2] == "победители" for r in got)
    assert ("МОШ", "информатика", "победители и призёры") in got
    assert ("ЮМШ", "математика", "победители и призёры") in got
    assert ("«Покори Воробьёвы горы!»", "математика", "победители") in got
    assert ("НТО", "информатика", "победители") in got
    assert ("«ТехноКубок»", "информатика", "победители") in got


def test_rebuild_only_when_data_or_parser_changed(built_database_url: str) -> None:
    """`--if-stale`: база, собранная текущими данными и кодом, не пересобирается; иначе — да."""
    from pathlib import Path

    from olymp_workers.ingest import build_fingerprint, is_current

    xlsx = str(Path(__file__).resolve().parents[3] / "data" / "Olimpiady_BVI_100ballov.xlsx")
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        stored = conn.execute("SELECT value FROM meta WHERE key = 'build_fingerprint'").fetchone()[
            0
        ]
    assert stored == build_fingerprint(xlsx)
    assert is_current(built_database_url, xlsx)

    try:
        with psycopg.connect(psycopg_dsn(built_database_url), autocommit=True) as conn:
            conn.execute("UPDATE meta SET value = 'старый-код' WHERE key = 'build_fingerprint'")
        assert not is_current(built_database_url, xlsx)  # код разбора или данные изменились
    finally:
        with psycopg.connect(psycopg_dsn(built_database_url), autocommit=True) as conn:
            conn.execute("UPDATE meta SET value = %s WHERE key = 'build_fingerprint'", (stored,))
    assert is_current(built_database_url, xlsx)


def test_fingerprint_depends_on_inputs(tmp_path) -> None:
    from olymp_workers.ingest import build_fingerprint

    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    a.write_bytes(b"1")
    b.write_bytes(b"2")
    assert build_fingerprint(str(a)) == build_fingerprint(str(a))
    assert build_fingerprint(str(a)) != build_fingerprint(str(b))


def test_olympiad_cards_loaded_with_sources(built_database_url: str) -> None:
    """Справочник олимпиад: карточки и треки привязаны к олимпиаде и профилю."""
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        cards = conn.execute("SELECT COUNT(*) FROM olympiad_info").fetchone()[0]
        no_source = conn.execute(
            "SELECT COUNT(*) FROM olympiad_info WHERE source_url NOT LIKE 'https://%'"
        ).fetchone()[0]
        mobile = conn.execute(
            """SELECT o.short_name, p.name FROM olympiad_tracks t
               JOIN olympiads o ON o.id = t.olympiad_id
               JOIN olympiad_profiles p ON p.id = t.profile_id
               WHERE t.name ILIKE '%мобильных приложений%'"""
        ).fetchall()
    assert cards >= 4
    assert no_source == 0
    assert mobile == [("«Юниор»", "инженерные науки")]


def _load(conn: psycopg.Connection, tmp_path: Path, card: dict) -> None:
    (tmp_path / CARDS_FILE).write_text(json.dumps({"olympiads": [card]}), encoding="utf-8")
    try:
        # база уже собрана с настоящими карточками: очищаем их внутри транзакции, откат вернёт
        conn.execute("TRUNCATE olympiad_tracks, olympiad_info")
        load_olympiad_cards(conn, tmp_path)
    finally:
        conn.rollback()


def test_card_with_unknown_olympiad_stops_build(built_database_url: str, tmp_path: Path) -> None:
    card = {**_CARD, "olympiad": "Олимпиады Хогвартса нет"}
    with (
        psycopg.connect(psycopg_dsn(built_database_url)) as conn,
        pytest.raises(CardError, match="Хогвартса.*нет в базе"),
    ):
        _load(conn, tmp_path, card)


def test_track_with_unknown_profile_stops_build(built_database_url: str, tmp_path: Path) -> None:
    track = {**_TRACK, "profile": "зельеварение"}
    with (
        psycopg.connect(psycopg_dsn(built_database_url)) as conn,
        pytest.raises(CardError, match="нет профиля «зельеварение»"),
    ):
        _load(conn, tmp_path, {**_CARD, "tracks": [track]})


_TRACK = {
    "name": "Секция",
    "profile": "инженерные науки",
    "source_url": "https://example.org",
    "checked": "2026-11-08",
}
_CARD = {
    "olympiad": "Всероссийский конкурс научных работ школьников «Юниор»",
    "site_url": "https://example.org",
    "summary": "x",
    "grades": "9–11",
    "format": ["проект"],
    "stages": [],
    "source_url": "https://example.org",
    "checked": "2026-11-08",
    "tracks": [_TRACK],
}


def test_cards_file_changes_build_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Правка карточки пересобирает базу при выкатке (--if-stale)."""
    from olymp_workers import ingest

    cards = tmp_path / CARDS_FILE
    cards.write_text('{"olympiads": []}', encoding="utf-8")
    monkeypatch.setattr(ingest, "DATA_DIR", tmp_path)
    before = ingest.build_fingerprint(ingest.DEFAULT_XLSX)
    cards.write_text('{"olympiads": [] }', encoding="utf-8")
    assert ingest.build_fingerprint(ingest.DEFAULT_XLSX) != before


def test_hse_pmi_vysshaya_proba_math_has_no_conflicting_conditions(
    built_database_url: str,
) -> None:
    """D2: у ПМИ ВШЭ (№3, 01.03.02) «Высшая проба» по математике — только победители, ЕГЭ ≥ 85.

    Строка «победители и призёры, ≥ 75» принадлежит другим программам с тем же кодом
    (№4 «Прикладной анализ данных», №5 «Компьютерные науки и анализ данных»): раньше все три
    программы склеивались по коду 01.03.02 и условия попадали на ПМИ вместе.
    """
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        rows = conn.execute(
            """SELECT p.faculty_or_direction, b.winner_role, b.min_ege
               FROM benefits b
               JOIN programs p ON p.id = b.program_id
               JOIN universities u ON u.id = p.university_id
               JOIN benefit_olympiads bo ON bo.benefit_id = b.id
               JOIN olympiads o ON o.id = bo.olympiad_id
               WHERE u.name = 'НИУ ВШЭ (Москва)' AND p.code = '01.03.02'
                 AND o.short_name = '«Высшая проба»' AND b.benefit_type = 'БВИ'
                 AND b.layer = 'detailed' AND b.olympiad_subject = 'математика'
               ORDER BY p.id, b.id"""
        ).fetchall()
    by_program: dict[str, set[tuple[str, str]]] = {}
    for program, role, min_ege in rows:
        by_program.setdefault(program, set()).add((role, min_ege))

    pmi = "№3. Прикладная математика и информатика (01.03.02)"
    assert by_program[pmi] == {("только победители", "85 и более")}
    # «≥ 75» достаётся программам, у которых оно записано в документе ВШЭ
    assert by_program["№4. Прикладной анализ данных (01.03.02)"] == {
        ("победители и призёры", "75 и более")
    }
    assert ("победители и призёры", "75 и более") in by_program[
        "№5. Компьютерные науки и анализ данных (01.03.02)"
    ]


def test_programs_with_same_code_are_not_merged(built_database_url: str) -> None:
    """D2: у ВШЭ (Москва) на одном коде несколько программ — каждая со своим номером."""
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        names = [
            row[0]
            for row in conn.execute(
                """SELECT p.faculty_or_direction FROM programs p
                   JOIN universities u ON u.id = p.university_id
                   WHERE u.name = 'НИУ ВШЭ (Москва)' AND p.code = '38.03.01'
                     AND p.source_sheet = 'База' ORDER BY p.id"""
            )
        ]
    assert any(n.startswith("№24. Экономика") for n in names)
    assert any(n.startswith("№25. Совместная программа") for n in names)
    assert len(names) >= 5


def test_urfu_profile_rules_keep_profile_and_confirm_subjects(built_database_url: str) -> None:
    """D1: «Астрономия (подтв.: математика, физика)» — профиль астрономия, а не математика."""
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        astronomy = conn.execute(
            """SELECT DISTINCT b.confirm_subject FROM benefits b
               JOIN programs p ON p.id = b.program_id
               JOIN universities u ON u.id = p.university_id
               WHERE u.name LIKE '%(УрФУ)' AND b.layer = 'derived' AND b.benefit_type = 'БВИ'
                 AND b.olympiad_profile = 'астрономия'"""
        ).fetchall()
        nto = conn.execute(
            """SELECT COUNT(DISTINCT p.id), COUNT(DISTINCT b.olympiad_profile),
                      COUNT(*) FILTER (
                          WHERE b.confirm_subject = 'биология, информатика, математика, физика, химия'
                      )
               FROM benefits b
               JOIN programs p ON p.id = b.program_id
               JOIN universities u ON u.id = p.university_id
               JOIN benefit_olympiads bo ON bo.benefit_id = b.id
               JOIN olympiads o ON o.id = bo.olympiad_id
               WHERE u.name LIKE '%(УрФУ)' AND b.layer = 'derived' AND o.short_name = 'НТО'"""
        ).fetchone()
    assert astronomy == [("математика, физика",)]
    # НТО (все профили) раньше давало 0 строк; теперь — профили НТО на направлениях УрФУ
    programs, profiles, with_nto_confirm = nto
    assert programs >= 50
    assert profiles >= 20
    # предметы подтверждения НТО взяты из скобок «(подтв.: …)» правила УрФУ
    assert with_nto_confirm >= 3000


def test_ege_requirements_are_parsed(built_database_url: str) -> None:
    """Пороги ЕГЭ разобраны в колонки при сборке: ≥ 95% непустых строк."""
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        nonempty, parsed, mismatched = conn.execute(
            """SELECT count(*),
                      count(*) FILTER (WHERE confirm_subjects IS NOT NULL),
                      count(*) FILTER (WHERE min_ege ~ '^\\d+' AND min_ege_score IS NULL
                                       AND confirm_subjects IS NOT NULL)
               FROM benefits
               WHERE confirm_subject NOT IN ('', '-') OR min_ege NOT IN ('', '-')"""
        ).fetchone()
        math = conn.execute(
            """SELECT confirm_subjects, min_ege_score FROM benefits
               WHERE confirm_subject = 'информатика, математика' AND min_ege = '75' LIMIT 1"""
        ).fetchone()
    assert parsed / nonempty >= 0.95
    assert mismatched == 0
    assert math == (["inf", "math"], 75)


def test_document_layer_rows_have_document_source(built_database_url: str) -> None:
    """Строки слоя document: источник — документ вуза со страницей и цитатой."""
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        total = conn.execute("SELECT COUNT(*) FROM benefits WHERE layer = 'document'").fetchone()[0]
        bad = conn.execute(
            """SELECT COUNT(*) FROM benefits WHERE layer = 'document'
               AND (source_url = '' OR source_title = '' OR source_page IS NULL OR source_quote = ''
                    OR row_key = '' OR NOT EXISTS (SELECT 1 FROM benefit_olympiads bo
                                                   WHERE bo.benefit_id = benefits.id))"""
        ).fetchone()[0]
        others = conn.execute(
            "SELECT COUNT(*) FROM benefits WHERE layer NOT IN ('document', 'derived')"
            " AND source_page IS NOT NULL"
        ).fetchone()[0]
    assert total == 5657
    assert (bad, others) == (0, 0)


def test_universities_without_tables_get_document_tables(built_database_url: str) -> None:
    """МАИ и МЭИ были почти пусты (два текстовых правила): теперь у них есть таблицы льгот,
    а «Высшая проба» в МАИ находится и в таблице, и в поиске."""
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        rows = dict(
            conn.execute(
                """SELECT u.short_name, COUNT(*) FROM benefits b
                   JOIN programs p ON p.id = b.program_id
                   JOIN universities u ON u.id = p.university_id
                   WHERE b.layer = 'document' GROUP BY u.short_name"""
            ).fetchall()
        )
        proba = conn.execute(
            """SELECT COUNT(*) FROM benefits b
               JOIN programs p ON p.id = b.program_id
               JOIN universities u ON u.id = p.university_id
               JOIN benefit_olympiads bo ON bo.benefit_id = b.id
               JOIN olympiads o ON o.id = bo.olympiad_id
               WHERE b.layer = 'document' AND u.short_name = 'МАИ' AND o.short_name LIKE '%проба%'"""
        ).fetchone()[0]
        indexed = conn.execute(
            """SELECT COUNT(*) FROM search_index s JOIN benefits b ON b.id = s.benefit_id
               JOIN programs p ON p.id = b.program_id JOIN universities u ON u.id = p.university_id
               WHERE b.layer = 'document' AND u.short_name = 'МАИ'
                 AND s.document @@ to_tsquery('simple', 'проба:*')"""
        ).fetchone()[0]
    assert rows["МАИ"] == 1378 and rows["НИУ «МЭИ»"] == 400
    assert proba > 0 and indexed > 0


def test_document_row_replaces_xlsx_twin(built_database_url: str) -> None:
    """Строка XLSX с тем же ключом (направление, олимпиада, профиль, тип) заменена документом."""
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        twins = conn.execute(
            """SELECT COUNT(*) FROM benefits d
               JOIN benefit_olympiads dbo ON dbo.benefit_id = d.id
               JOIN benefits x ON x.program_id = d.program_id AND x.benefit_type = d.benefit_type
                                  AND x.layer IN ('detailed', 'derived')
               JOIN benefit_olympiads xbo ON xbo.benefit_id = x.id
                                             AND xbo.olympiad_id = dbo.olympiad_id
                                             AND xbo.profile = dbo.profile
               WHERE d.layer = 'document'"""
        ).fetchone()[0]
    assert twins == 0


def test_document_records_survive_rebuild() -> None:
    from olymp_db.models import DATA_TABLES

    assert "document_records" not in DATA_TABLES
