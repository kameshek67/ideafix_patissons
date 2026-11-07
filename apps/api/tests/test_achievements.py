"""«Мои дипломы» на базе из настоящего XLSX: подбор льгот, вход через MAX, хранение дипломов."""

import json
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote, urlencode

import httpx
import pytest
from olymp_api.main import create_app
from olymp_api.max_auth import InitDataError, sign, validate_init_data
from olymp_api.settings import Settings
from olymp_db.models import DATA_TABLES

TOKEN = "test-bot-token"


def init_data(user_id: int, *, token: str = TOKEN, auth_date: int | None = None) -> str:
    params = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "chat": json.dumps({"id": 1, "type": "DIALOG"}),
        "query_id": "4c0ab423-342b-4e45-aea4-2747dbc500cd",
        "user": json.dumps(
            {
                "id": user_id,
                "first_name": "Маша",
                "last_name": "Иванова",
                "username": None,
                "language_code": "ru",
                "photo_url": None,
            },
            ensure_ascii=False,
        ),
    }
    params["hash"] = sign(params, token)
    return urlencode(params, quote_via=quote)


@pytest.fixture
async def max_client(built_database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        Settings(
            _env_file=None,
            database_url=built_database_url,
            rate_limit_requests=0,
            max_bot_token=TOKEN,
            max_bot_name="olymp_bot",
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()


async def form(client: httpx.AsyncClient, q: str) -> dict[str, Any]:
    olympiad = (await client.get("/v1/olympiads", params={"q": q, "limit": 1})).json()["items"][0]
    response = await client.get(f"/v1/achievements/olympiads/{olympiad['id']}")
    assert response.status_code == 200
    data: dict[str, Any] = response.json()
    return data


def spec(data: dict[str, Any], profile: str | None, rest: str) -> str:
    key = next(p["key"] for p in data["profiles"] if p["name"] == profile) if profile else "-"
    return f"{data['olympiad']['key']}.{key}.{rest}"


async def match(client: httpx.AsyncClient, *diplomas: str, **params: Any) -> dict[str, Any]:
    response = await client.get(
        "/v1/achievements/match", params={"diploma": list(diplomas), **params}
    )
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


# ---------------------------------------------------------------- форма диплома


async def test_diploma_form_profiles(client: httpx.AsyncClient) -> None:
    hse = await form(client, "вышка")
    assert hse["olympiad"]["short_name"] == "«Высшая проба»"
    assert hse["olympiad"]["key"].endswith("высшаяпроба")
    assert "математика" in [p["name"] for p in hse["profiles"]]

    vsosh = await form(client, "всош")
    names = [p["name"] for p in vsosh["profiles"]]
    assert "математика" in names and "английский язык" in names
    # обрывки разбора таблиц в форму не попадают
    assert "баллов" not in names and "профили: нет" not in names
    assert (await client.get("/v1/achievements/olympiads/999999")).status_code == 404


# ---------------------------------------------------------------- подбор


async def test_conditions_narrow_the_result(client: httpx.AsyncClient) -> None:
    hse = await form(client, "вышка")
    winner = await match(client, spec(hse, "математика", "w.11.2025"))
    prize = await match(client, spec(hse, "математика", "p.11.2025"))
    tenth = await match(client, spec(hse, "математика", "p.10.2025"))
    old = await match(client, spec(hse, "математика", "p.11.2021"))

    assert winner["totals"]["programs"] > 100 and winner["totals"]["bvi"] > 100
    assert winner["diplomas"][0]["found"] and not winner["diplomas"][0]["expired"]
    # «только победители» призёру не положены; диплом за 10 класс подходит не везде
    assert prize["rejected"]["role"] > 0
    assert prize["totals"]["programs"] <= winner["totals"]["programs"]
    assert tenth["rejected"]["grade"] > prize["rejected"]["grade"]
    assert tenth["totals"]["programs"] < prize["totals"]["programs"]
    # дипломы старше четырёх лет льгот не дают
    assert old["diplomas"][0]["expired"]
    assert old["totals"]["programs"] == 0 and old["rejected"]["year"] > 0

    # итоги вуза складываются из лучших льгот направлений
    for u in winner["results"]:
        assert u["programs"] == u["bvi"] + u["sto"] + u["other"] > 0
    assert sum(u["programs"] for u in winner["results"]) == winner["totals"]["programs"]
    bvi_first = [u["bvi"] for u in winner["results"]]
    assert bvi_first == sorted(bvi_first, reverse=True)


async def test_vsosh_matches_by_subject(client: httpx.AsyncClient) -> None:
    vsosh = await form(client, "всош")
    math = await match(client, spec(vsosh, "математика", "p.11.2026"))
    english = await match(client, spec(vsosh, "английский язык", "w.11.2026"))
    assert math["totals"]["programs"] > 50
    # в таблицах вузов язык часто записан как «иностранный язык»
    assert english["totals"]["sto"] > 50

    top = math["results"][0]["university"]["id"]
    rows = (await match(client, spec(vsosh, "математика", "p.11.2026"), university_id=top))["rows"]
    assert rows and {r["fit"] for r in rows} <= {"exact", "subject", "check"}


async def test_university_rows(client: httpx.AsyncClient) -> None:
    hse = await form(client, "вышка")
    diploma = spec(hse, "математика", "w.11.2025")
    listing = await match(client, diploma)
    top = listing["results"][0]
    detail = await match(client, diploma, university_id=top["university"]["id"])

    assert detail["university"]["id"] == top["university"]["id"]
    assert len({r["program"]["id"] for r in detail["rows"]}) == top["programs"]
    for row in detail["rows"]:
        assert row["diplomas"] == [0]
        assert row["benefit"]["olympiads"][0]["id"] == hse["olympiad"]["id"]
        assert row["benefit"]["matched"]["role"] is not None
    assert listing["rows"] == [] and listing["university"] is None


async def test_benefit_type_filter_and_several_diplomas(client: httpx.AsyncClient) -> None:
    hse = await form(client, "вышка")
    vsosh = await form(client, "всош")
    one = spec(hse, "математика", "w.11.2025")
    two = spec(vsosh, "математика", "p.11.2026")
    bvi = await match(client, one, benefit_type="БВИ")
    assert bvi["totals"]["sto"] == 0 and bvi["totals"]["bvi"] > 0

    both = await match(client, one, two, one)  # повтор убирается
    assert [d["spec"] for d in both["diplomas"]] == [one, two]
    single = await match(client, one)
    assert both["totals"]["programs"] >= single["totals"]["programs"]


async def test_unknown_or_broken_diplomas(client: httpx.AsyncClient) -> None:
    unknown = await match(client, "несуществующаяолимпиада.-.w.0.0")
    assert unknown["diplomas"][0]["found"] is False
    assert unknown["totals"]["programs"] == 0 and unknown["results"] == []

    bad = await client.get("/v1/achievements/match", params={"diploma": "abc"})
    assert bad.status_code == 422
    assert bad.headers["content-type"].startswith("application/problem+json")
    many = [f"олимпиада.-.w.0.{2000 + i}" for i in range(21)]
    assert (await client.get("/v1/achievements/match", params={"diploma": many})).status_code == 422


# ---------------------------------------------------------------- вход через MAX


def test_init_data_signature() -> None:
    raw = init_data(42)
    user = validate_init_data(raw, TOKEN, max_age=3600)
    assert (user.id, user.first_name, user.username) == (42, "Маша", "")

    with pytest.raises(InitDataError):
        validate_init_data(raw, "other-token", max_age=3600)
    with pytest.raises(InitDataError):
        validate_init_data(raw.replace("42", "43", 1), TOKEN, max_age=3600)
    with pytest.raises(InitDataError):
        validate_init_data(raw + "&auth_date=1", TOKEN, max_age=3600)
    with pytest.raises(InitDataError):
        validate_init_data(init_data(42, auth_date=1_000_000), TOKEN, max_age=3600)
    # max_age=0 — срок не проверяется
    assert validate_init_data(init_data(42, auth_date=1_000_000), TOKEN, max_age=0).id == 42


async def test_me_requires_configured_bot(client: httpx.AsyncClient) -> None:
    config = (await client.get("/v1/max/config")).json()
    assert config["enabled"] is False and config["valid_years"] == [2023, 2024, 2025, 2026]
    response = await client.get("/v1/me/diplomas", headers={"X-Max-Init-Data": init_data(1)})
    assert response.status_code == 503


async def test_me_rejects_bad_init_data(max_client: httpx.AsyncClient) -> None:
    assert (await max_client.get("/v1/me/diplomas")).status_code == 401
    forged = {"X-Max-Init-Data": init_data(1, token="stolen")}
    assert (await max_client.get("/v1/me/diplomas", headers=forged)).status_code == 401


async def test_me_diplomas_round_trip(max_client: httpx.AsyncClient) -> None:
    config = (await max_client.get("/v1/max/config")).json()
    assert config["enabled"] is True and config["bot_name"] == "olymp_bot"

    headers = {"X-Max-Init-Data": init_data(9_000_001)}
    empty = (await max_client.get("/v1/me/diplomas", headers=headers)).json()
    assert empty["user"]["id"] == 9_000_001 and empty["diplomas"] == []

    hse = await form(max_client, "вышка")
    diplomas = [spec(hse, "математика", "w.11.2025"), spec(hse, None, "p.0.0")]
    saved = await max_client.put("/v1/me/diplomas", headers=headers, json={"diplomas": diplomas})
    assert saved.status_code == 200
    assert [d["spec"] for d in saved.json()["diplomas"]] == diplomas
    assert saved.json()["diplomas"][0]["profile_name"] == "математика"

    again = (await max_client.get("/v1/me/diplomas", headers=headers)).json()
    assert [d["spec"] for d in again["diplomas"]] == diplomas
    # другой пользователь чужих дипломов не видит
    other = {"X-Max-Init-Data": init_data(9_000_002)}
    assert (await max_client.get("/v1/me/diplomas", headers=other)).json()["diplomas"] == []

    replaced = await max_client.put(
        "/v1/me/diplomas", headers=headers, json={"diplomas": diplomas[1:]}
    )
    assert [d["spec"] for d in replaced.json()["diplomas"]] == diplomas[1:]
    broken = await max_client.put("/v1/me/diplomas", headers=headers, json={"diplomas": ["x"]})
    assert broken.status_code == 422
    await max_client.put("/v1/me/diplomas", headers=headers, json={"diplomas": []})


def test_user_tables_survive_rebuild() -> None:
    # olymp-ingest очищает только таблицы данных сборки
    assert "max_users" not in DATA_TABLES and "user_diplomas" not in DATA_TABLES
