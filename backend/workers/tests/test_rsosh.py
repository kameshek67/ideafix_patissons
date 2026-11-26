"""Перечень олимпиад РСОШ на 2026/27: разбор страницы и перенос в базу."""

import json
from pathlib import Path

import psycopg
import pytest
from olymp_db.session import psycopg_dsn
from olymp_workers import ingest, rsosh

FIXTURE = Path(__file__).parent / "fixtures" / "rsosh_table.html"
DATA = Path(__file__).resolve().parents[3] / "data" / rsosh.RSOSH_FILE


def test_parse_table_expands_rowspans() -> None:
    rows = rsosh.parse_table(FIXTURE.read_text(encoding="utf-8"))
    assert [(r["number"], r["profile"], r["level"]) for r in rows] == [
        (1, "рисунок, живопись", "I"),
        (2, "гуманитарные и социальные науки", "I"),
        (2, "экономика", "III"),
        (3, "инфохимия", "III"),
        (3, "искусственный интеллект", "II"),
        (3, "виртуальная реальность", "II"),
    ]
    # название тянется на все строки блока, переводы строк и пробелы схлопнуты
    assert (
        rows[2]["olympiad"]
        == "Всероссийская академическая олимпиада школьников имени В.И. Вернадского"
    )
    assert {r["olympiad"] for r in rows[3:]} == {"«Национальная технологическая олимпиада»"}
    assert rows[1]["subjects"] == "история, обществознание"
    assert rows[2]["subjects"] == "экономика"


def test_parse_table_rejects_unknown_level_and_broken_rows() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    with pytest.raises(rsosh.RsoshError, match="уровень"):
        rsosh.parse_table(html.replace("<td>II</td>", "<td>?</td>"))
    with pytest.raises(rsosh.RsoshError, match="не хватает"):
        rsosh.parse_table(html.replace("<td>экономика</td>\n\t\t\t\t<td>экономика</td>", ""))


def test_build_refuses_a_page_without_the_table() -> None:
    with pytest.raises(rsosh.RsoshError, match="строк"):
        rsosh.build("<html><body>перечень переехал</body></html>")
    with pytest.raises(rsosh.RsoshError, match="строк"):
        rsosh.build(FIXTURE.read_text(encoding="utf-8"))  # три-четыре строки — не перечень


def test_committed_file_is_complete() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    assert data["source_url"] == "https://rsr-olymp.ru/"
    rows = rsosh.load(DATA)
    assert len(rows) == len(data["rows"]) >= rsosh.MIN_ROWS
    assert len({r["olympiad"] for r in rows}) >= 50
    assert {r["level"] for r in rows} == {"I", "II", "III"}
    assert all(r["profile"] and r["subjects"] for r in rows)


def test_load_missing_or_broken_file(tmp_path: Path) -> None:
    assert rsosh.load(tmp_path / "нет.json") == []
    broken = tmp_path / "broken.json"
    broken.write_text('{"rows": [{"olympiad": "x"}]}', encoding="utf-8")
    with pytest.raises(rsosh.RsoshError, match="повреждён"):
        rsosh.load(broken)


def test_every_list_olympiad_is_matched(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        listed = dict(
            conn.execute(
                "SELECT short_name, in_rsosh_2026_27 FROM olympiads WHERE in_rsosh_2026_27"
            ).fetchall()
        )
    names = {r["olympiad"] for r in rsosh.load(DATA)}
    # две строки перечня («по геологии» и «Открытая…») сходятся в одну олимпиаду справочника
    assert len(listed) >= len(names) - 1
    assert {"«Высшая проба»", "НТО", "«Ломоносов»", "МОШ"} <= set(listed)


def test_olympiads_outside_the_list_are_flagged(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        flags = dict(conn.execute("SELECT short_name, in_rsosh_2026_27 FROM olympiads").fetchall())
        kinds = dict(conn.execute("SELECT short_name, kind FROM olympiads").fetchall())
    for name in ("«Когнитивные технологии»", "«Робофест»", "«САММАТ»", "«Океан знаний»"):
        assert flags[name] is False, name
    assert flags["«Формула Единства»/«Третье тысячелетие»"] is False
    # перечень не применим: ВсОШ и настоящие международные олимпиады
    assert flags["ВсОШ"] is None
    assert flags["Международная олимпиада по информатике"] is None
    assert all(flags[n] is None for n, k in kinds.items() if k in ("vsosh", "other"))


def test_profile_levels_come_from_the_list(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        rows = conn.execute(
            """SELECT o.short_name, p.name, p.level, p.level_2026_27
               FROM olympiad_profiles p JOIN olympiads o ON o.id = p.olympiad_id"""
        ).fetchall()
    levels = {(o, name): (old, new) for o, name, old, new in rows}
    # в перечне 2026/27 «Высшая проба» по химии — I (в документах вузов было II)
    assert levels[("«Высшая проба»", "химия")] == ("II", "I")
    assert levels[("«Ломоносов»", "иностранный язык")] == ("I", "II")
    # пары, которых в перечне нет, остаются без уровня
    assert sum(1 for _, new in levels.values() if new) >= 250
    assert all(new in ("", "I", "II", "III") for _, new in levels.values())


def test_apply_list_reports_what_did_not_match(built_database_url: str) -> None:
    rows = [
        {"number": 1, "olympiad": "Олимпиада «Ломоносов»", "profile": "нет такого", "level": "I"},
        {"number": 2, "olympiad": "Несуществующая олимпиада", "profile": "x", "level": "II"},
    ]
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        lomonosov = conn.execute(
            "SELECT id FROM olympiads WHERE short_name = '«Ломоносов»'"
        ).fetchone()[0]
        log: list[str] = []
        stats = rsosh.apply_list(
            conn, rows, lambda name: lomonosov if "Ломоносов" in name else None, log.append
        )
        flagged = conn.execute("SELECT COUNT(*) FROM olympiads WHERE in_rsosh_2026_27").fetchone()[
            0
        ]
        conn.rollback()  # база сессионная: чужим тестам нужны данные сборки
    assert (stats["matched_olympiads"], stats["unmatched_olympiads"]) == (1, 1)
    assert stats["levels"] == 0 and stats["missing_profiles"] == 1
    assert flagged == 1
    assert any("нет в справочнике: «Несуществующая олимпиада»" in line for line in log)
    assert any("нет профиля в базе" in line and "нет такого" in line for line in log)


def test_list_file_changes_build_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xlsx = str(ingest.DEFAULT_XLSX)
    before = ingest.build_fingerprint(xlsx)
    data = tmp_path / "data"
    data.mkdir()
    (data / rsosh.RSOSH_FILE).write_text('{"rows": []}', encoding="utf-8")
    monkeypatch.setattr(ingest, "DATA_DIR", data)
    assert ingest.build_fingerprint(xlsx) != before
