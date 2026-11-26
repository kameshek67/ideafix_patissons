"""«Нашли ошибку в данных»: сообщение сохраняется с названиями экрана, лимит работает."""

import json
import time
from urllib.parse import quote, urlencode

import httpx
import psycopg
import pytest
from olymp_api.main import create_app
from olymp_api.max_auth import sign
from olymp_api.settings import Settings
from olymp_db.session import psycopg_dsn


async def first_program(client: httpx.AsyncClient) -> dict:
    hse = (await client.get("/v1/universities", params={"q": "НИУ ВШЭ (Москва)"})).json()["items"][
        0
    ]
    params = {"university_id": hse["id"], "q": "01.03.02"}
    return (await client.get("/v1/programs", params=params)).json()["items"][0]


async def test_report_is_saved_with_screen_names(
    client: httpx.AsyncClient, built_database_url: str
) -> None:
    program = await first_program(client)
    body = {
        "kind": "program",
        "program_id": program["id"],
        "message": "  У «Высшей пробы» не тот уровень  ",
    }
    created = await client.post("/v1/reports", json=body)
    assert created.status_code == 201
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        kind, context, message = conn.execute(
            "SELECT kind, context, message FROM data_reports WHERE id = %s", (created.json()["id"],)
        ).fetchone()
    assert kind == "program" and message == "У «Высшей пробы» не тот уровень"
    assert context["university"] == "НИУ ВШЭ (Москва)" and context["code"] == "01.03.02"

    olympiad = (await client.get("/v1/olympiads", params={"q": "вышка", "limit": 1})).json()[
        "items"
    ][0]
    report = {"kind": "olympiad", "olympiad_id": olympiad["id"], "message": "Нет льготы в МФТИ"}
    assert (await client.post("/v1/reports", json=report)).status_code == 201


async def test_report_validation(client: httpx.AsyncClient) -> None:
    short = {"kind": "program", "program_id": 1, "message": "ой"}
    assert (await client.post("/v1/reports", json=short)).status_code == 422
    missing = {"kind": "olympiad", "olympiad_id": 999_999, "message": "Ошибка в данных"}
    assert (await client.post("/v1/reports", json=missing)).status_code == 404
    other = {"kind": "diplomas", "message": json.dumps({"x": 1})}
    assert (await client.post("/v1/reports", json=other)).status_code == 422


async def test_report_rate_limit(built_database_url: str) -> None:
    settings = Settings(
        _env_file=None, database_url=built_database_url, rate_limit_requests=0, report_rate_limit=2
    )
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        program = await first_program(c)
        body = {"kind": "program", "program_id": program["id"], "message": "Ошибка в строке"}
        codes = [(await c.post("/v1/reports", json=body)).status_code for _ in range(3)]
    await app.state.engine.dispose()
    assert codes == [201, 201, 429]


# ---------------------------------------------------------------- «Не совпадает с документом»

BOT_TOKEN = "test-bot-token"


def init_data(user_id: int, *, token: str) -> str:
    """Подписанные данные запуска мини-приложения, как их шлёт MAX."""
    params = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": user_id, "first_name": "Маша"}, ensure_ascii=False),
    }
    params["hash"] = sign(params, token)
    return urlencode(params, quote_via=quote)


async def some_row(client: httpx.AsyncClient) -> dict:
    """Любая строка льготы из выдачи: у неё есть ключ."""
    program = await first_program(client)
    data = (await client.get("/v1/search/by-program", params={"program_id": program["id"]})).json()
    row = data["groups"][0]["rows"][0]
    assert row["row_key"] and row["fixed_at"] is None
    return row


async def test_benefit_report_context_comes_from_database(
    client: httpx.AsyncClient, built_database_url: str
) -> None:
    row = await some_row(client)
    body = {
        "kind": "benefit",
        "row_key": row["row_key"],
        "reason": "winners_only",
        "message": "",
        "link": "https://example.test/doc.pdf",
        # лишнее от клиента сервер не принимает за контекст
        "context": {"university": "Выдуманный вуз"},
    }
    created = await client.post("/v1/reports", json=body)
    assert created.status_code == 201
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        kind, key, reason, link, source, status, user, context = conn.execute(
            """SELECT kind, row_key, reason, link, source, status, max_user_id, context
               FROM data_reports WHERE id = %s""",
            (created.json()["id"],),
        ).fetchone()
    assert (kind, key, reason, source, status) == (
        "benefit",
        row["row_key"],
        "winners_only",
        "user",
        "new",
    )
    assert link == "https://example.test/doc.pdf" and user is None
    assert context["university"] == "НИУ ВШЭ (Москва)" and context["code"] == "01.03.02"
    assert context["benefit_type"] == row["benefit_type"] and context["olympiad"]


async def test_benefit_report_validation(client: httpx.AsyncClient) -> None:
    row = await some_row(client)
    key = row["row_key"]
    post = lambda **extra: client.post(  # noqa: E731
        "/v1/reports", json={"kind": "benefit", "row_key": key, "reason": "other", **extra}
    )
    assert (await post()).status_code == 201  # комментарий и ссылка необязательны
    assert (await post(reason="что-то")).status_code == 422
    assert (await post(link="javascript:alert(1)")).status_code == 422
    assert (await post(message="x" * 1001)).status_code == 422
    missing = {"kind": "benefit", "row_key": "нет-такой", "reason": "other"}
    assert (await client.post("/v1/reports", json=missing)).status_code == 404


async def test_benefit_report_remembers_max_user(built_database_url: str) -> None:
    app = create_app(
        Settings(
            _env_file=None,
            database_url=built_database_url,
            rate_limit_requests=0,
            max_bot_token=BOT_TOKEN,
        )
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        row = await some_row(c)
        body = {"kind": "benefit", "row_key": row["row_key"], "reason": "no_benefit"}
        headers = {"X-Max-Init-Data": init_data(4242, token=BOT_TOKEN)}
        known = await c.post("/v1/reports", json=body, headers=headers)
        forged = await c.post(
            "/v1/reports", json=body, headers={"X-Max-Init-Data": init_data(7, token="чужой")}
        )
    await app.state.engine.dispose()
    assert known.status_code == forged.status_code == 201
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        users = {
            report_id: user
            for report_id, user in conn.execute("SELECT id, max_user_id FROM data_reports")
        }
    assert users[known.json()["id"]] == 4242
    assert users[forged.json()["id"]] is None  # подпись не сошлась: жалоба принята как анонимная


async def test_fixed_row_carries_mark(client: httpx.AsyncClient, built_database_url: str) -> None:
    row = await some_row(client)
    created = await client.post(
        "/v1/reports", json={"kind": "benefit", "row_key": row["row_key"], "reason": "wrong_ege"}
    )
    report_id = created.json()["id"]
    program = await first_program(client)

    def rows() -> list[dict]:
        return [r for g in data["groups"] for r in g["rows"] if r["row_key"] == row["row_key"]]

    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        for status in ("checking", "fixed"):
            conn.execute(
                "UPDATE data_reports SET status = %s, resolved_at = now() WHERE id = %s",
                (status, report_id),
            )
            conn.commit()
            data = (
                await client.get("/v1/search/by-program", params={"program_id": program["id"]})
            ).json()
            marks = {r["fixed_at"] is not None for r in rows()}
            assert marks == {status == "fixed"}


async def test_correct_status_needs_quote(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        report_id = conn.execute(
            """INSERT INTO data_reports (kind, context, message, source)
               VALUES ('program', '{}', 'Ошибка', 'monitor') RETURNING id"""
        ).fetchone()[0]
        conn.commit()
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE data_reports SET status = 'correct' WHERE id = %s", (report_id,))
        conn.rollback()
        conn.execute(
            "UPDATE data_reports SET status = 'correct', quote = 'п. 3: БВИ' WHERE id = %s",
            (report_id,),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE data_reports SET source = 'кто-то' WHERE id = %s", (report_id,))
        conn.rollback()
