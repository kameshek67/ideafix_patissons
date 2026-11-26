"""Стабильный ключ строки льготы и снимок выдачи."""

import random
from dataclasses import replace
from pathlib import Path

import psycopg
from olymp_db.session import psycopg_dsn
from olymp_workers.row_keys import RowFields, assign_row_keys
from olymp_workers.snapshot import build_snapshot, diff_lines, render, summary

XLSX = Path(__file__).resolve().parents[3] / "data" / "Olimpiady_BVI_100ballov.xlsx"


def _row(row_id: int, **fields) -> RowFields:
    base = RowFields(
        id=row_id,
        university="МГУ",
        program_code="01.03.02",
        program_name="Прикладная математика",
        benefit_type="БВИ",
        layer="detailed",
        olympiads=("lomonosov",),
        profile="математика",
        level="1",
        role="победитель",
        grade="11",
        ege_subject="математика",
        ege_min="75",
        source="https://example.org/doc",
        tiebreak=("текст",),
    )
    return replace(base, **fields)


def test_key_ignores_id_and_olympiad_order() -> None:
    a = _row(1, olympiads=("b", "a"))
    b = _row(500, olympiads=("a", "b"))
    assert a.base_key() == b.base_key()
    assert _row(1, ege_min="80").base_key() != a.base_key()
    assert _row(1, layer="derived").base_key() != a.base_key()


def test_twins_get_suffix_independent_of_insertion_order() -> None:
    rows = [_row(i, tiebreak=(f"текст {i % 3}",)) for i in range(1, 8)]
    rows.append(_row(100, ege_min="80"))
    expected = {tuple(r.tiebreak) + (r.ege_min,): None for r in rows}
    reference = assign_row_keys(rows)
    assert len(set(reference.values())) == len(rows)

    by_content = {}
    for row in rows:
        by_content.setdefault((row.ege_min, tuple(row.tiebreak)), []).append(reference[row.id])
    assert len(by_content) == len(expected)

    rng = random.Random(7)
    for _ in range(5):
        shuffled = rows[:]
        rng.shuffle(shuffled)
        # те же строки под другими id: ключи по содержимому не меняются
        renumbered = [replace(r, id=r.id + 1000) for r in shuffled]
        again = assign_row_keys(renumbered)
        for row in renumbered:
            same = [
                reference[r.id]
                for r in rows
                if (r.ege_min, r.tiebreak) == (row.ege_min, row.tiebreak)
            ]
            assert again[row.id].split("-")[0] == same[0].split("-")[0]
        assert sorted(again.values()) == sorted(reference.values())


def test_build_gives_unique_keys_and_same_snapshot_twice(built_database_url: str) -> None:
    from olymp_workers.ingest import Ingestor

    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        total, distinct, empty = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT row_key), COUNT(*) FILTER (WHERE row_key = '')"
            " FROM benefits"
        ).fetchone()
        first = build_snapshot(conn)
    assert total == distinct
    assert empty == 0

    Ingestor(str(XLSX), built_database_url).run()
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        second = build_snapshot(conn)
    assert first == second


def test_snapshot_diff_summary(tmp_path: Path) -> None:
    old = ["a\t1", "b\t2", "c\t3"]
    new = ["a\t1", "c\t3", "d\t4", "e\t5"]
    plus, minus = diff_lines(old, new)
    assert plus == ["d\t4", "e\t5"]
    assert minus == ["b\t2"]
    text = summary(plus, minus)
    assert "+2 добавлено" in text and "−1 удалено" in text
    assert "+ d\t4" in text and "− b\t2" in text

    path = tmp_path / "s.tsv"
    path.write_text(render(old), encoding="utf-8")
    from olymp_workers.snapshot import read_snapshot

    assert read_snapshot(path) == old
