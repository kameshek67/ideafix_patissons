"""API на базе, собранной из настоящего XLSX. Полная сверка с прототипом —
scripts/compare_with_prototype.py; здесь — контракт и основные сценарии."""

import httpx
import pytest
from olymp_api.main import create_app
from olymp_api.settings import Settings


async def test_health(client: httpx.AsyncClient) -> None:
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    ready = (await client.get("/readyz")).json()
    assert ready["status"] == "ready" and ready["built_at"]


async def test_stats(client: httpx.AsyncClient) -> None:
    data = (await client.get("/v1/stats")).json()
    assert data["totals"]["universities"] == 39
    assert data["totals"]["rows"] == 48973
    assert len(data["universities"]) == 39
    assert len(data["top_olympiads"]) == 15
    assert data["sheets"][0]["sheet"] == "База"


async def test_regions_order(client: httpx.AsyncClient) -> None:
    names = [g["name"] for g in (await client.get("/v1/regions")).json()["items"]]
    assert names == ["Москва", "Санкт-Петербург", "Регионы"]


async def test_universities_and_programs(client: httpx.AsyncClient) -> None:
    unis = (await client.get("/v1/universities", params={"region": "Москва"})).json()
    assert unis["count"] > 0
    assert {u["region_group"] for u in unis["items"]} == {"Москва"}
    hse = next(u for u in unis["items"] if u["name"] == "НИУ ВШЭ (Москва)")

    programs = (await client.get("/v1/programs", params={"university_id": hse["id"]})).json()
    assert programs["count"] == hse["programs"]
    found = (
        await client.get("/v1/programs", params={"university_id": hse["id"], "q": "01.03.02"})
    ).json()
    assert found["count"] >= 1
    assert all(
        "01.03.02" in p["code"] or "01.03.02" in p["faculty_or_direction"] for p in found["items"]
    )


@pytest.mark.parametrize(
    ("query", "expected"),
    [("пвг", "«Покори Воробьёвы горы!»"), ("вышка", "«Высшая проба»"), ("всош", "ВсОШ")],
)
async def test_olympiad_aliases(client: httpx.AsyncClient, query: str, expected: str) -> None:
    items = (await client.get("/v1/olympiads", params={"q": query, "limit": 5})).json()["items"]
    assert items[0]["short_name"] == expected
    assert items[0]["rank"] == 0
    assert items[0]["profiles"] > 0


async def test_profiles(client: httpx.AsyncClient) -> None:
    nto = (await client.get("/v1/olympiads", params={"q": "нто"})).json()["items"][0]
    data = (await client.get(f"/v1/olympiads/{nto['id']}/profiles")).json()
    assert data["olympiad"]["id"] == nto["id"]
    assert data["count"] == len(data["items"]) > 10
    mentions = [p["mentions"] for p in data["items"]]
    assert mentions == sorted(mentions, reverse=True)


async def test_search_ignores_case(client: httpx.AsyncClient) -> None:
    async def names(q: str) -> list[str]:
        data = (await client.get("/v1/universities", params={"q": q})).json()
        return [u["name"] for u in data["items"]]

    assert await names("мгу") == await names("МГУ") != []
    hse = (await client.get("/v1/universities", params={"q": "ниу вшэ (москва)"})).json()
    university_id = hse["items"][0]["id"]

    async def programs(q: str) -> int:
        params = {"university_id": university_id, "q": q}
        return len((await client.get("/v1/programs", params=params)).json()["items"])

    assert await programs("МАТЕМАТИКА") == await programs("математика") > 0
    # % в запросе — обычный символ, а не «что угодно»
    assert await programs("%") == 0


async def test_by_program(client: httpx.AsyncClient) -> None:
    hse = (await client.get("/v1/universities", params={"q": "НИУ ВШЭ (Москва)"})).json()["items"][
        0
    ]
    program = (
        await client.get("/v1/programs", params={"university_id": hse["id"], "q": "01.03.02"})
    ).json()["items"][0]
    data = (await client.get("/v1/search/by-program", params={"program_id": program["id"]})).json()
    assert data["program"]["id"] == program["id"]
    assert data["university"]["name"] == "НИУ ВШЭ (Москва)"
    types = [g["type"] for g in data["groups"]]
    assert types[0] == "БВИ"
    assert data["total_benefits"] == sum(g["count"] for g in data["groups"])
    assert data["sources"][0]["kind"] == "page"
    row = data["groups"][0]["rows"][0]
    assert row["olympiads"] and row["layer"] in ("detailed", "derived")


async def test_by_program_not_found(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/search/by-program", params={"program_id": 10**9})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Направление не найдено"


async def test_by_olympiad_list_and_university(client: httpx.AsyncClient) -> None:
    olympiad = (await client.get("/v1/olympiads", params={"q": "вышка"})).json()["items"][0]
    params = {"q": olympiad["short_name"], "olympiad_id": olympiad["id"]}
    data = (await client.get("/v1/search/by-olympiad", params=params)).json()
    assert data["matched_olympiads"][0]["id"] == olympiad["id"]
    assert data["total_universities"] == len(data["results"]) > 1
    totals = [r["bvi"] + r["sto"] + r["other"] for r in data["results"]]
    assert totals == sorted(totals, reverse=True)

    bvi_only = (
        await client.get("/v1/search/by-olympiad", params={**params, "benefit_type": "БВИ"})
    ).json()
    assert all(r["sto"] == 0 for r in bvi_only["results"])

    uni = data["results"][0]["university"]
    one = (
        await client.get("/v1/search/by-olympiad", params={**params, "university_id": uni["id"]})
    ).json()
    assert [r["university"]["id"] for r in one["results"]] == [uni["id"]]
    benefit = one["results"][0]["programs"][0]["benefits"][0]
    assert benefit["matched"]["via"] in ("column", "text")


async def test_by_olympiad_fallback(client: httpx.AsyncClient) -> None:
    data = (await client.get("/v1/search/by-olympiad", params={"q": "абракадабра"})).json()
    assert data["matched_olympiads"] == []
    assert data["fallback"] == []
    # слово из условий, но не название олимпиады — запасной полнотекстовый поиск
    words = (await client.get("/v1/search/by-olympiad", params={"q": "робототехника"})).json()
    assert words["matched_olympiads"] == [] and words["fallback"]


async def test_validation_error_is_problem_json(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/search/by-olympiad", params={"q": "a"})
    assert response.status_code == 422
    assert response.json()["title"] == "Validation error"


async def test_rate_limit(built_database_url: str) -> None:
    app = create_app(
        Settings(_env_file=None, database_url=built_database_url, rate_limit_requests=2)
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        codes = [(await c.get("/v1/regions")).status_code for _ in range(3)]
        assert (await c.get("/healthz")).status_code == 200  # служебные пути без лимита
    await app.state.engine.dispose()
    assert codes == [200, 200, 429]


async def test_without_database() -> None:
    app = create_app(Settings(_env_file=None, database_url=None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/v1/stats")).status_code == 503


async def test_table_rows_separate_text_rules_from_tables(client: httpx.AsyncClient) -> None:
    """У МФТИ в базе только текстовое правило: `table_rows` = 0, чтобы интерфейс не писал «0 БВИ»."""
    items = {u["short_name"]: u for u in (await client.get("/v1/universities")).json()["items"]}
    assert items["МФТИ"]["table_rows"] == 0 and items["МФТИ"]["benefits"] > 0
    assert items["НИУ ВШЭ (Москва)"]["table_rows"] > 1000
    programs = (
        await client.get("/v1/programs", params={"university_id": items["МФТИ"]["id"]})
    ).json()
    assert programs["items"] and all(p["table_rows"] == 0 for p in programs["items"])
