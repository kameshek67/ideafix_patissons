"""«Поделиться» (F-01) на базе из настоящего XLSX: снимки, открытие, лимиты, пересборка."""

import re
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from olymp_api.main import create_app
from olymp_api.settings import Settings
from olymp_db.models import DATA_TABLES, Base
from olymp_domain.program_key import program_stable_key, university_key
from sqlalchemy import create_engine, text

TOKEN = re.compile(r"^[A-Za-z0-9]{10}$")
XLSX = Path(__file__).resolve().parents[3] / "data" / "Olimpiady_BVI_100ballov.xlsx"
HSE = "НИУ ВШЭ (Москва)"


async def share(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await client.post("/v1/shares", json=body)


async def hse_and_program(client: httpx.AsyncClient) -> tuple[dict[str, Any], dict[str, Any]]:
    unis = (await client.get("/v1/universities")).json()["items"]
    hse = next(u for u in unis if u["name"] == HSE)
    params = {"university_id": hse["id"], "q": "01.03.02"}
    program = (await client.get("/v1/programs", params=params)).json()["items"][0]
    return hse, program


async def vysshaya_proba(client: httpx.AsyncClient) -> tuple[dict[str, Any], dict[str, Any]]:
    olympiad = (await client.get("/v1/olympiads", params={"q": "вышка", "limit": 1})).json()
    olympiad = olympiad["items"][0]
    profiles = (await client.get(f"/v1/olympiads/{olympiad['id']}/profiles")).json()["items"]
    return olympiad, next(p for p in profiles if p["name"] == "математика")


async def make_client(database_url: str, **settings: Any) -> httpx.AsyncClient:
    app = create_app(
        Settings(_env_file=None, database_url=database_url, rate_limit_requests=0, **settings)
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------- снимки и открытие


async def test_program_share_round_trip(client: httpx.AsyncClient) -> None:
    _, program = await hse_and_program(client)
    first = await share(client, kind="program", program_id=program["id"], benefit_type="БВИ")
    assert first.status_code == 201, first.text
    created = first.json()
    assert TOKEN.match(created["token"])
    assert created["web_path"] == f"/s/{created['token']}"
    assert created["max_url"] is None  # бот MAX не настроен

    # тот же экран — та же ссылка; другой фильтр — другой экран
    again = await share(client, kind="program", program_id=program["id"], benefit_type="БВИ")
    assert again.status_code == 200 and again.json()["token"] == created["token"]
    other = await share(client, kind="program", program_id=program["id"])
    assert other.json()["token"] != created["token"]

    opened = (await client.get(f"/v1/shares/{created['token']}")).json()
    assert opened == {
        "kind": "program",
        "benefit_type": "БВИ",
        "found": True,
        "resolved": {
            "program_id": program["id"],
            "olympiad": None,
            "profile_id": None,
            "university": None,
            "diplomas": [],
        },
    }


async def test_olympiad_share(client: httpx.AsyncClient) -> None:
    hse, _ = await hse_and_program(client)
    olympiad, math = await vysshaya_proba(client)
    body = {
        "kind": "olympiad",
        "olympiad_id": olympiad["id"],
        "profile_id": math["id"],
        "university_id": hse["id"],
    }
    token = (await share(client, **body)).json()["token"]
    data = (await client.get(f"/v1/shares/{token}")).json()
    assert data["kind"] == "olympiad" and data["found"] and data["benefit_type"] is None
    resolved = data["resolved"]
    assert resolved["olympiad"] == {"id": olympiad["id"], "short_name": olympiad["short_name"]}
    assert resolved["profile_id"] == math["id"]
    assert resolved["university"]["id"] == hse["id"] and resolved["university"]["name"] == HSE

    only = await share(
        client, kind="olympiad", olympiad_id=olympiad["id"], benefit_type="100 баллов"
    )
    resolved = (await client.get(f"/v1/shares/{only.json()['token']}")).json()["resolved"]
    assert resolved["profile_id"] is None and resolved["university"] is None

    wrong_profile = {"kind": "olympiad", "olympiad_id": olympiad["id"], "profile_id": 999999}
    assert (await share(client, **wrong_profile)).status_code == 404
    assert (await share(client, kind="olympiad", olympiad_id=999999)).status_code == 404


async def test_diplomas_share(client: httpx.AsyncClient) -> None:
    olympiad, _ = await vysshaya_proba(client)
    form = (await client.get(f"/v1/achievements/olympiads/{olympiad['id']}")).json()
    key = form["olympiad"]["key"]
    profile = next(p for p in form["profiles"] if p["name"] == "математика")
    specs = [
        f"{key}.{profile['key']}.w.11.2025",
        f"{key}.-.p.0.0",
        "несуществующаяолимпиада.-.w.0.0",
    ]

    created = await share(client, kind="diplomas", diplomas=[*specs, specs[0]])
    assert created.status_code == 201, created.text
    data = (await client.get(f"/v1/shares/{created.json()['token']}")).json()
    assert data["kind"] == "diplomas" and data["found"]
    # названия кладёт сервер из базы; диплом, которого нет в базе, остаётся как есть
    assert data["resolved"]["diplomas"] == [
        {"spec": specs[0], "olympiad": olympiad["short_name"], "profile": "математика"},
        {"spec": specs[1], "olympiad": olympiad["short_name"], "profile": ""},
        {"spec": specs[2], "olympiad": "", "profile": ""},
    ]

    unknown = await share(client, kind="diplomas", diplomas=["несуществующаяолимпиада.-.w.0.0"])
    assert unknown.status_code == 422
    assert (await share(client, kind="diplomas", diplomas=["abc"])).status_code == 422
    assert (await share(client, kind="diplomas", diplomas=[])).status_code == 422
    many = [f"{key}.-.w.0.{year}" for year in range(2000, 2021)]
    assert (await share(client, kind="diplomas", diplomas=many)).status_code == 422


async def test_broken_requests_and_unknown_token(client: httpx.AsyncClient) -> None:
    assert (await share(client, kind="nope", program_id=1)).status_code == 422
    assert (
        await share(client, kind="program", program_id=1, benefit_type="Все")
    ).status_code == 422
    assert (await share(client, kind="program", program_id=999999)).status_code == 404

    missing = await client.get("/v1/shares/AAAAAAAAAA")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert (await client.get("/v1/shares/short")).status_code == 422


async def test_expired_link_and_open_counter(
    client: httpx.AsyncClient, built_database_url: str
) -> None:
    _, program = await hse_and_program(client)
    body = {"kind": "program", "program_id": program["id"], "benefit_type": "100 баллов"}
    token = (await share(client, **body)).json()["token"]
    for _ in range(2):
        assert (await client.get(f"/v1/shares/{token}")).status_code == 200

    engine = create_engine(built_database_url)
    with engine.begin() as conn:
        sql = "SELECT opened_count FROM share_links WHERE token = :t"
        assert conn.execute(text(sql), {"t": token}).scalar() == 2
        conn.execute(
            text("UPDATE share_links SET expires_at = now() - interval '1 day' WHERE token = :t"),
            {"t": token},
        )
    engine.dispose()
    assert (await client.get(f"/v1/shares/{token}")).status_code == 404
    # устаревшая ссылка удаляется, тот же экран получает новую
    renewed = await share(client, **body)
    assert renewed.status_code == 201 and renewed.json()["token"] != token


async def test_share_rate_limit(built_database_url: str) -> None:
    async with await make_client(built_database_url, share_rate_limit=2) as c:
        _, program = await hse_and_program(c)
        responses = [await share(c, kind="program", program_id=program["id"]) for _ in range(3)]
        assert [r.status_code for r in responses[1:]] == [200, 429]
        assert int(responses[2].headers["Retry-After"]) > 0


async def test_max_link_when_bot_configured(built_database_url: str) -> None:
    async with await make_client(
        built_database_url, max_bot_token="test-bot-token", max_bot_name="olymp_bot"
    ) as c:
        _, program = await hse_and_program(c)
        created = (await share(c, kind="program", program_id=program["id"])).json()
        assert created["max_url"] == f"https://max.ru/olymp_bot?startapp=s_{created['token']}"


# ---------------------------------------------------------------- ключи и пересборка


def test_program_and_university_keys_are_unique(built_database_url: str) -> None:
    engine = create_engine(built_database_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """SELECT u.name, p.faculty_or_direction, p.profile_name, p.code
                   FROM programs p JOIN universities u ON u.id = p.university_id"""
            )
        ).all()
        universities = [r[0] for r in conn.execute(text("SELECT name FROM universities"))]
    engine.dispose()
    keys = Counter(program_stable_key(*row) for row in rows)
    assert len(rows) > 600
    assert [key for key, n in keys.items() if n > 1] == []
    assert len({university_key(name) for name in universities}) == len(universities)


def test_share_links_survive_data_tables() -> None:
    """Пользовательские таблицы не ссылаются на таблицы сборки: TRUNCATE … CASCADE при
    пересборке иначе молча очистил бы и их."""
    assert "share_links" not in DATA_TABLES
    for table in Base.metadata.sorted_tables:
        if table.name in DATA_TABLES:
            continue
        for fk in table.foreign_keys:
            assert fk.column.table.name not in DATA_TABLES, (table.name, fk.target_fullname)


async def test_links_open_same_objects_after_rebuild(
    client: httpx.AsyncClient, built_database_url: str
) -> None:
    """Пересборка базы меняет id, а ссылки открывают те же объекты. Тест идёт последним
    в файле: пересобирает общую тестовую базу (с тем же XLSX)."""
    from olymp_workers.ingest import Ingestor

    hse, program = await hse_and_program(client)
    olympiad, math = await vysshaya_proba(client)
    program_token = (await share(client, kind="program", program_id=program["id"])).json()["token"]
    olympiad_body = {
        "kind": "olympiad",
        "olympiad_id": olympiad["id"],
        "profile_id": math["id"],
        "university_id": hse["id"],
    }
    olympiad_token = (await share(client, **olympiad_body)).json()["token"]

    engine = create_engine(built_database_url)
    with engine.begin() as conn:
        links = conn.execute(text("SELECT count(*) FROM share_links")).scalar()
        # с тем же XLSX сборка выдала бы те же id — сдвигаем начало последовательностей,
        # иначе тест не отличил бы ссылку по ключам от ссылки по id
        for table in ("universities", "programs", "olympiads", "olympiad_profiles"):
            conn.execute(text(f"ALTER SEQUENCE {table}_id_seq START WITH 100000"))
    Ingestor(str(XLSX), built_database_url).run()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM share_links")).scalar() == links
        new_program_id = conn.execute(
            text(
                """SELECT p.id FROM programs p JOIN universities u ON u.id = p.university_id
                   WHERE u.name = :u AND p.faculty_or_direction = :n AND p.profile_name = :pr
                     AND p.code = :c"""
            ),
            {
                "u": HSE,
                "n": program["faculty_or_direction"],
                "pr": program["profile_name"],
                "c": program["code"],
            },
        ).scalar()
    engine.dispose()
    assert new_program_id is not None and new_program_id != program["id"]

    opened = (await client.get(f"/v1/shares/{program_token}")).json()
    assert opened["found"] and opened["resolved"]["program_id"] == new_program_id

    new_olympiad, new_math = await vysshaya_proba(client)
    assert new_olympiad["id"] != olympiad["id"]
    resolved = (await client.get(f"/v1/shares/{olympiad_token}")).json()["resolved"]
    assert resolved["olympiad"]["id"] == new_olympiad["id"]
    assert resolved["profile_id"] == new_math["id"]
    assert resolved["university"]["name"] == HSE and resolved["university"]["id"] != hse["id"]
