"""Бот-оператор на подставном API MAX и настоящей базе: уведомления, кнопки, ответы авторам."""

import json
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from olymp_db.session import psycopg_dsn
from olymp_workers import report_regressions
from olymp_workers.max_bot import hint, run
from olymp_workers.max_operator import Operator, Reports, operator_ids
from psycopg.rows import dict_row

OPERATORS = frozenset({101, 102})
CONTEXT = {
    "university": "НИУ ВШЭ (Москва)",
    "code": "01.03.02",
    "program": "Прикладная математика",
    "olympiad": "Высшая проба",
    "benefit_type": "БВИ",
    "level": "I",
    "source_url": "https://example.test/doc.pdf",
}


class MaxApi:
    """Поддельный API MAX: события отдаёт один раз, всё отправленное запоминает."""

    def __init__(self, updates: list[dict[str, Any]] | None = None, fail_for: int | None = None):
        self.updates = list(updates or [])
        self.fail_for = fail_for
        self.sent: list[tuple[str, dict[str, Any] | None, dict[str, Any] | None]] = []

    def __call__(
        self, method: str, path: str, query: dict[str, Any] | None, body: dict[str, Any] | None
    ) -> Any:
        if path == "/me":
            return {"user_id": 1, "username": "olymp_bot", "is_bot": True}
        if path == "/updates":
            updates, self.updates = self.updates, []
            return {"updates": updates, "marker": 1}
        if self.fail_for is not None and (query or {}).get("user_id") == self.fail_for:
            from olymp_workers.max_bot import MaxApiError

            raise MaxApiError("HTTP 403: бот заблокирован")
        self.sent.append((path, query, body))
        return {}

    def to(self, user_id: int) -> list[dict[str, Any]]:
        return [
            body
            for path, query, body in self.sent
            if path == "/messages" and query["user_id"] == user_id
        ]


def add_report(conn: psycopg.Connection, **values: Any) -> int:
    fields = {
        "kind": "benefit",
        "context": json.dumps(CONTEXT, ensure_ascii=False),
        "message": "",
        "row_key": "abc123def456",
        "reason": "winners_only",
        **values,
    }
    columns = ", ".join(fields)
    marks = ", ".join(["%s"] * len(fields))
    row = conn.execute(
        f"INSERT INTO data_reports ({columns}) VALUES ({marks}) RETURNING id",  # noqa: S608
        list(fields.values()),
    ).fetchone()
    assert row
    conn.commit()
    return row[0]


@pytest.fixture
def db(empty_database_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        conn.execute("DELETE FROM data_reports")
        conn.execute("DELETE FROM share_links")
        conn.commit()
        yield conn


@pytest.fixture
def operator(empty_database_url: str, db: psycopg.Connection) -> Operator:
    dsn = psycopg_dsn(empty_database_url)
    return Operator(
        ids=OPERATORS,
        reports=Reports(lambda: psycopg.connect(dsn, row_factory=dict_row)),
        api_url="http://api.test",
        fetch_json=lambda url: {"enabled": True} if url.endswith("config") else {"status": "ready"},
    )


def status_of(conn: psycopg.Connection, report_id: int) -> tuple[str, str, Any]:
    row = conn.execute(
        "SELECT status, quote, resolved_at FROM data_reports WHERE id = %s", (report_id,)
    ).fetchone()
    assert row
    return row


def command(text: str, user_id: int = 101) -> dict[str, Any]:
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": user_id, "first_name": "Дежурный", "is_bot": False},
            "recipient": {"chat_id": 5, "chat_type": "dialog", "user_id": 1},
            "body": {"mid": "mid.1", "text": text},
        },
    }


def press(payload: str, user_id: int = 101) -> dict[str, Any]:
    return {
        "update_type": "message_callback",
        "callback": {"callback_id": "cb1", "payload": payload, "user": {"user_id": user_id}},
    }


def test_operator_ids_parse() -> None:
    assert operator_ids("12, 34;56,,x") == frozenset({12, 34, 56})
    assert operator_ids("") == operator_ids(None) == frozenset()


def test_others_get_the_usual_reply(operator: Operator) -> None:
    api = MaxApi([command("/reports", user_id=7), command("/stats", user_id=7)])
    assert run(api, once=True, operator=operator) == 2
    assert api.to(7) == [hint("olymp_bot"), hint("olymp_bot")]


def test_new_report_goes_to_every_operator_once(operator: Operator, db: psycopg.Connection) -> None:
    number = add_report(db)
    api = MaxApi()
    assert run(api, once=True, operator=operator) == 2
    for user in OPERATORS:
        (message,) = api.to(user)
        assert message["text"].startswith("Новая жалоба")
        assert f"№{number}" in message["text"] and "только для победителей" in message["text"]
        assert (
            "Высшая проба" in message["text"] and "https://example.test/doc.pdf" in message["text"]
        )
        payloads = [
            b["payload"] for row in message["attachments"][0]["payload"]["buttons"] for b in row
        ]
        assert payloads == [
            f"r:{number}:{s}" for s in ("checking", "fixed", "correct", "duplicate")
        ]
    assert run(MaxApi(), once=True, operator=operator) == 0  # повторно не рассылаем


def test_blocked_operator_does_not_stop_the_rest(
    operator: Operator, db: psycopg.Connection
) -> None:
    add_report(db)
    api = MaxApi(fail_for=101)
    assert run(api, once=True, operator=operator) == 1
    assert api.to(102) and run(MaxApi(), once=True, operator=operator) == 0  # 4xx — не повторяем


def test_reports_command_and_buttons(operator: Operator, db: psycopg.Connection) -> None:
    first = add_report(db, operator_notified_at="2026-01-01")
    second = add_report(db, operator_notified_at="2026-01-01", status="checking")
    closed = add_report(db, status="duplicate")
    api = MaxApi([command("/reports")])
    run(api, once=True, operator=operator)
    head, *cards = api.to(101)
    assert head["text"] == "Открытых жалоб: 2"
    assert [f"№{n}" in c["text"] for c, n in zip(cards, (first, second), strict=True)] == [
        True,
        True,
    ]
    assert all(f"№{closed}" not in c["text"] for c in cards)

    api = MaxApi([press(f"r:{first}:checking")])
    run(api, once=True, operator=operator)
    ((path, query, body),) = api.sent
    assert (path, query) == ("/answers", {"callback_id": "cb1"})
    assert "проверяем" in body["message"]["text"] and body["message"]["attachments"]
    assert status_of(db, first)[0] == "checking" and status_of(db, first)[2] is None

    api = MaxApi([press(f"r:{first}:fixed")])
    run(api, once=True, operator=operator)
    ((_, _, body),) = api.sent
    assert body["message"]["attachments"] == []  # у закрытой жалобы кнопок нет
    assert status_of(db, first)[0] == "fixed" and status_of(db, first)[2] is not None


def test_correct_needs_a_quote(operator: Operator, db: psycopg.Connection) -> None:
    number = add_report(db, operator_notified_at="2026-01-01")
    api = MaxApi([press(f"r:{number}:correct"), command(f"/quote {number}"), command("/quote x")])
    run(api, once=True, operator=operator)
    answer, ask, no_quote, bad_format = api.sent
    assert answer[2] == {"notification": "Нужна цитата из документа"}
    assert f"/quote {number}" in ask[2]["text"]
    assert "нужна цитата" in no_quote[2]["text"] and "Формат" in bad_format[2]["text"]
    assert status_of(db, number)[0] == "new"

    api = MaxApi([command(f"/quote {number} п. 4.2: БВИ только победителям")])
    run(api, once=True, operator=operator)
    assert status_of(db, number)[:2] == ("correct", "п. 4.2: БВИ только победителям")
    assert "Цитата из документа" in api.to(101)[0]["text"]


def test_unknown_report_and_foreign_button(operator: Operator, db: psycopg.Connection) -> None:
    api = MaxApi([press("r:9999:fixed"), press("r:9999:correct"), press("r:1:fixed", user_id=7)])
    run(api, once=True, operator=operator)
    assert [b["notification"] for _, _, b in api.sent] == ["Жалобы №9999 нет.", "Жалобы №9999 нет"]


def test_author_from_max_gets_an_answer(operator: Operator, db: psycopg.Connection) -> None:
    known = add_report(db, operator_notified_at="2026-01-01", max_user_id=555)
    anonymous = add_report(db, operator_notified_at="2026-01-01")
    run(MaxApi([press(f"r:{known}:checking")]), once=True, operator=operator)
    api = MaxApi()
    run(api, once=True, operator=operator)
    assert api.sent == []  # «проверяем» автору не пишем

    api = MaxApi([press(f"r:{known}:fixed"), press(f"r:{anonymous}:fixed")])
    run(api, once=True, operator=operator)
    (reply,) = api.to(555)
    assert "Высшая проба" in reply["text"] and "исправили" in reply["text"]
    assert [q for p, q, _ in api.sent if p == "/messages"] == [{"user_id": 555}]  # аноним — тишина
    assert run(MaxApi(), once=True, operator=operator) == 0  # на тот же статус второй раз не пишем

    api = MaxApi([command(f"/quote {known} п. 3")])
    run(api, once=True, operator=operator)  # ответ автору уходит в том же круге
    assert "в таблице всё верно" in api.to(555)[0]["text"] and "п. 3" in api.to(555)[0]["text"]


def test_stats_say_no_data_where_nothing_is_recorded(
    operator: Operator, db: psycopg.Connection
) -> None:
    add_report(db, operator_notified_at="2026-01-01")
    fixed = add_report(db, operator_notified_at="2026-01-01")
    old = add_report(db, operator_notified_at="2026-01-01", status="duplicate")
    db.execute(
        "UPDATE data_reports SET created_at = now() - interval '3 days' WHERE id = %s", (old,)
    )
    db.execute(
        "INSERT INTO share_links (token, kind, payload, payload_hash, expires_at) "
        "VALUES ('t1', 'diplomas', '{}', 'h1', now() + interval '1 day')"
    )
    db.commit()
    run(MaxApi([press(f"r:{fixed}:fixed")]), once=True, operator=operator)

    api = MaxApi([command("/stats")])
    run(api, once=True, operator=operator)
    (text,) = [m["text"] for m in api.to(101)]
    assert "Поиски: нет данных" in text and "Пустые выдачи: нет данных" in text
    assert "новых 2, закрыто 1 (исправлено 1" in text and "открытых сейчас 1" in text
    assert "«Поделиться»: новых ссылок 1" in text


def test_health(operator: Operator) -> None:
    api = MaxApi([command("/health")])
    run(api, once=True, operator=operator)
    text = api.to(101)[0]["text"]
    assert "API: ок" in text and "База: ок" in text and "Помощник: включён" in text

    def down(url: str) -> Any:
        raise OSError("нет связи")

    operator.fetch_json = down
    assert "API: не отвечает" in operator.health() and "неизвестно" in operator.health()
    operator.fetch_json = lambda url: {"enabled": False}
    assert "Помощник: выключен" in operator.health()


def test_without_operator_nothing_changes() -> None:
    api = MaxApi([command("/reports")])
    assert run(api, once=True) == 1 and api.to(101) == [hint("olymp_bot")]


# ---------------------------------------------------------------- регрессии


def test_fixed_reports_become_scenarios(
    built_database_url: str, tmp_path: Any, empty_database_url: str
) -> None:
    path = tmp_path / "reports.json"
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        conn.execute("DELETE FROM data_reports")
        fixed = add_report(conn, status="fixed", resolved_at="2026-11-26 10:00+00")
        add_report(conn, status="new", row_key="other")
        add_report(conn, status="fixed", kind="program", row_key="")
        assert report_regressions.export(conn, path) == 1
        data = json.loads(path.read_text(encoding="utf-8"))
        scenario = data["scenarios"][0]
        assert scenario["report_id"] == fixed and scenario["row_key"] == "abc123def456"
        assert scenario["expect"] == "absent" and scenario["context"]["university"].startswith(
            "НИУ"
        )
        # повторная выгрузка не затирает ручные правки
        scenario["expect"] = "present"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert report_regressions.export(conn, path) == 1
        assert report_regressions.load(path)[0]["expect"] == "present"

    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        key = conn.execute("SELECT row_key FROM benefits WHERE layer <> 'raw' LIMIT 1").fetchone()[
            0
        ]
        assert report_regressions.check(conn, report_regressions.load(path)) == [
            f"№{fixed} (НИУ ВШЭ (Москва)): строка abc123def456 пропала из выдачи"
        ]
        back = [{"report_id": 9, "row_key": key, "expect": "absent", "context": {}}]
        assert "снова в выдаче" in report_regressions.check(conn, back)[0]
        assert report_regressions.check(conn, [{**back[0], "expect": "present"}]) == []


def test_committed_scenarios_hold(built_database_url: str) -> None:
    """Сценарии из data/regressions/reports.json: исправленные строки не вернулись."""
    scenarios = report_regressions.load(report_regressions.DEFAULT_PATH)
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        assert report_regressions.check(conn, scenarios) == []
