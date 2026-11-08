"""«Нашли ошибку в данных»: сообщение сохраняется с названиями экрана, лимит работает (T-079)."""

import json

import httpx
import psycopg
from olymp_api.main import create_app
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
