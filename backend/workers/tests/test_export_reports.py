"""olymp_workers.export_reports: защита CSV от формул, --mark-seen трогает только выгруженное."""

import io

import psycopg
import pytest
from olymp_db.session import psycopg_dsn
from olymp_workers import export_reports


@pytest.mark.parametrize("bad", ["=1+1", "+7 495", "-2+3", "@SUM(A1)", "\tтаб", "\rвозврат"])
def test_formula_like_values_are_escaped(bad: str) -> None:
    assert export_reports.safe_cell(bad) == "'" + bad


@pytest.mark.parametrize("fine", ["Ошибка в данных", "", "1=1", 42, None])
def test_regular_values_stay_as_is(fine: object) -> None:
    assert export_reports.safe_cell(fine) == fine


def add_report(conn: psycopg.Connection, message: str, status: str = "new") -> int:
    row = conn.execute(
        "INSERT INTO data_reports (kind, context, message, status) "
        "VALUES ('program', '{\"university\": \"=HYPERLINK(1)\"}', %s, %s) RETURNING id",
        (message, status),
    ).fetchone()
    assert row
    return row[0]


def statuses(conn: psycopg.Connection) -> dict[int, str]:
    return dict(conn.execute("SELECT id, status FROM data_reports").fetchall())


def test_export_escapes_cells_and_marks_only_exported(empty_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        conn.execute("DELETE FROM data_reports")
        first = add_report(conn, "=cmd|' /C calc'!A0")
        done = add_report(conn, "Уже разобрано", status="fixed")
        out = io.StringIO()

        original = conn.execute
        late: list[int] = []

        def execute(query, *args, **kwargs):  # noqa: ANN001, ANN202
            result = original(query, *args, **kwargs)
            if str(query).startswith("SELECT") and not late:
                late.append(add_report(conn, "Пришло во время выгрузки"))
            return result

        conn.execute = execute  # type: ignore[method-assign]
        count = export_reports.export(conn, out, include_all=True, mark_seen=True)
        conn.execute = original  # type: ignore[method-assign]

        assert count == 2
        assert "'=cmd|" in out.getvalue() and "'=HYPERLINK(1)" in out.getvalue()
        assert statuses(conn) == {first: "seen", done: "fixed", late[0]: "new"}
