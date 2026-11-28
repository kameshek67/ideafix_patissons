"""Краевые случаи каталога и баллов за индивидуальные достижения."""

from collections.abc import Mapping

import httpx
import pytest
from olymp_api.main import create_app
from olymp_api.modules.catalog.synonyms import name_fragments
from olymp_api.settings import Settings

YEAR = 2026
HUGE_ID = 10**30
LONG_QUERY = "а" * 201


def assert_problem(response: httpx.Response, status: int, title: str) -> None:
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "about:blank"
    assert body["title"] == title
    assert body["status"] == status
    assert body["instance"] == response.request.url.path
    assert body["request_id"] == response.headers["x-request-id"]


async def assert_validation(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    params: Mapping[str, object] | None = None,
    body: object = None,
) -> None:
    response = await client.request(method, path, params=params, json=body)
    assert_problem(response, 422, "Validation error")
    errors = response.json()["errors"]
    assert errors
    assert all({"loc", "msg", "type"} <= set(error) for error in errors)


async def first_university_id(client: httpx.AsyncClient) -> int:
    items = (await client.get("/v1/universities")).json()["items"]
    return items[0]["id"]


async def test_stats_and_regions_on_empty_database(empty_database_url: str) -> None:
    app = create_app(
        Settings(_env_file=None, database_url=empty_database_url, rate_limit_requests=0)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        stats = await client.get("/v1/stats")
        assert_problem(stats, 503, "База ещё не собрана: запустите olymp-ingest")
        regions = await client.get("/v1/regions")
        assert regions.status_code == 200
        assert regions.json() == {"items": []}
    await app.state.engine.dispose()


async def test_universities_empty_search(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/v1/universities", params={"region": "Нет такого региона", "q": "абракадабра"}
    )
    body = response.json()
    assert response.status_code == 200
    assert body["count"] == 0 and body["items"] == []
    assert body["regions"] == ["Москва", "Санкт-Петербург", "Регионы"]


async def test_universities_all_region(client: httpx.AsyncClient) -> None:
    plain = (await client.get("/v1/universities")).json()
    every = (await client.get("/v1/universities", params={"region": "Все"})).json()
    assert every == plain
    assert every["count"] == len(every["items"]) > 0


@pytest.mark.parametrize(("q", "status"), [("а" * 200, 200), (LONG_QUERY, 422)])
async def test_universities_query_length(client: httpx.AsyncClient, q: str, status: int) -> None:
    response = await client.get("/v1/universities", params={"q": q})
    assert response.status_code == status
    if status == 200:
        assert response.json()["items"] == []
    else:
        assert_problem(response, 422, "Validation error")


async def test_programs_unknown_university(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/programs", params={"university_id": 999999})
    assert response.status_code == 200
    assert response.json() == {"count": 0, "items": []}


async def test_programs_zero_university_id(client: httpx.AsyncClient) -> None:
    await assert_validation(client, "GET", "/v1/programs", params={"university_id": 0})


@pytest.mark.parametrize(("limit", "status"), [(1, 200), (2000, 200), (0, 422), (2001, 422)])
async def test_programs_limit_boundaries(
    client: httpx.AsyncClient, limit: int, status: int
) -> None:
    university_id = await first_university_id(client)
    response = await client.get(
        "/v1/programs", params={"university_id": university_id, "limit": limit}
    )
    assert response.status_code == status
    if status == 200:
        body = response.json()
        assert 0 < len(body["items"]) <= limit
        assert body["count"] == len(body["items"])
    else:
        assert_problem(response, 422, "Validation error")


@pytest.mark.parametrize(
    "params",
    [{"university_id": "abc"}, {"university_id": 1.5}, {"q": LONG_QUERY}],
)
async def test_programs_invalid_params(
    client: httpx.AsyncClient, params: dict[str, object]
) -> None:
    await assert_validation(client, "GET", "/v1/programs", params=params)


@pytest.mark.parametrize("q", ["абракадабра", "а", "👻"])
async def test_olympiads_empty_search(client: httpx.AsyncClient, q: str) -> None:
    response = await client.get("/v1/olympiads", params={"q": q})
    assert response.status_code == 200
    assert response.json() == {"count": 0, "items": []}


@pytest.mark.parametrize(("limit", "status"), [(1, 200), (200, 200), (0, 422), (201, 422)])
async def test_olympiads_limit_boundaries(
    client: httpx.AsyncClient, limit: int, status: int
) -> None:
    response = await client.get("/v1/olympiads", params={"limit": limit})
    assert response.status_code == status
    if status == 200:
        body = response.json()
        assert 0 < len(body["items"]) <= limit
        assert body["count"] == len(body["items"])
    else:
        assert_problem(response, 422, "Validation error")


@pytest.mark.parametrize(
    "params",
    [{"featured": "maybe"}, {"with_profile": "maybe"}, {"q": LONG_QUERY}],
)
async def test_olympiads_invalid_params(
    client: httpx.AsyncClient, params: dict[str, object]
) -> None:
    await assert_validation(client, "GET", "/v1/olympiads", params=params)


async def test_olympiads_featured_filter(client: httpx.AsyncClient) -> None:
    featured = (await client.get("/v1/olympiads", params={"featured": "true", "limit": 5})).json()
    plain = (await client.get("/v1/olympiads", params={"limit": 5})).json()
    assert featured["items"]
    assert all(item["is_featured"] == 1 for item in featured["items"])
    assert plain["count"] >= featured["count"]


@pytest.mark.parametrize("olympiad_id", [999999, -1])
async def test_olympiad_profiles_not_found(client: httpx.AsyncClient, olympiad_id: int) -> None:
    response = await client.get(f"/v1/olympiads/{olympiad_id}/profiles")
    assert_problem(response, 404, "Олимпиада не найдена")


@pytest.mark.parametrize("olympiad_id", ["abc", "1.5"])
async def test_olympiad_profiles_invalid_id(client: httpx.AsyncClient, olympiad_id: str) -> None:
    await assert_validation(client, "GET", f"/v1/olympiads/{olympiad_id}/profiles")


@pytest.mark.parametrize("admission_year", [2000, 2100])
async def test_extra_universities_year_boundaries(
    client: httpx.AsyncClient, admission_year: int
) -> None:
    response = await client.get(
        "/v1/extra-points/universities", params={"admission_year": admission_year}
    )
    assert response.status_code == 200
    assert response.json() == {"admission_year": admission_year, "items": []}


@pytest.mark.parametrize(
    "params",
    [{}, {"admission_year": 1999}, {"admission_year": 2101}, {"admission_year": "x"}],
)
async def test_extra_universities_invalid_year(
    client: httpx.AsyncClient, params: dict[str, object]
) -> None:
    await assert_validation(client, "GET", "/v1/extra-points/universities", params=params)


@pytest.mark.parametrize("university_id", [999999, 0, -1])
async def test_extra_rules_unknown_university(
    client: httpx.AsyncClient, university_id: int
) -> None:
    response = await client.get(
        f"/v1/extra-points/universities/{university_id}", params={"admission_year": YEAR}
    )
    assert_problem(response, 404, "Вуз не найден")


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/v1/extra-points/universities/1", {}),
        ("/v1/extra-points/universities/1", {"admission_year": 1999}),
        ("/v1/extra-points/universities/abc", {"admission_year": YEAR}),
    ],
)
async def test_extra_rules_invalid_params(
    client: httpx.AsyncClient, path: str, params: dict[str, object]
) -> None:
    await assert_validation(client, "GET", path, params=params)


async def test_extra_rules_year_without_data(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/extra-points/universities/1", params={"admission_year": 2030})
    body = response.json()
    assert response.status_code == 200
    assert body["university_id"] == 1 and body["admission_year"] == 2030
    assert body["max_total"] is None and body["max_total_source"] is None
    assert body["rules"] == []


@pytest.mark.parametrize("university_id", [999999, 0])
async def test_score_unknown_university(client: httpx.AsyncClient, university_id: int) -> None:
    response = await client.post(
        "/v1/extra-points/score",
        json={"university_id": university_id, "admission_year": YEAR, "claims": []},
    )
    assert_problem(response, 404, "Вуз не найден")


async def test_score_empty_claims(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/extra-points/score",
        json={"university_id": 1, "admission_year": YEAR, "claims": []},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "scored"
    assert body["total"] == 0 and body["raw_total"] == 0
    assert body["awards"] == [] and body["unmatched"] == []
    assert body["capped"] is False and body["unverified"] is False


@pytest.mark.parametrize("year", [2000, 2100])
async def test_score_claim_year_boundaries(client: httpx.AsyncClient, year: int) -> None:
    response = await client.post(
        "/v1/extra-points/score",
        json={
            "university_id": 1,
            "admission_year": YEAR,
            "claims": [{"kind": "gto_badge", "variant": "нет-такого-значка", "year": year}],
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["admission_year"] == YEAR and body["total"] == 0
    assert body["awards"] == [] and len(body["unmatched"]) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"university_id": 1, "admission_year": 1999, "claims": []},
        {"university_id": 1, "admission_year": 2101, "claims": []},
        {"university_id": 1, "admission_year": YEAR},
        {
            "university_id": 1,
            "admission_year": YEAR,
            "claims": [{"kind": "gto_badge", "year": 1999}],
        },
        {
            "university_id": 1,
            "admission_year": YEAR,
            "claims": [{"kind": "gto_badge", "variant": "х" * 41}],
        },
        {"university_id": 1, "admission_year": YEAR, "claims": [{"kind": "gto_badge"}] * 41},
    ],
)
async def test_score_invalid_body(client: httpx.AsyncClient, body: dict[str, object]) -> None:
    await assert_validation(client, "POST", "/v1/extra-points/score", body=body)


async def test_max_config_ignores_query_and_rejects_post(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/max/config", params={"admission_year": "abc", "limit": 0})
    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"enabled", "bot_name", "campaign_year", "admission_year", "valid_years"}
    assert body["valid_years"] and body["admission_year"] >= max(body["valid_years"])
    wrong_method = await client.post("/v1/max/config")
    assert_problem(wrong_method, 405, "Method Not Allowed")


@pytest.mark.parametrize(
    ("path", "params", "expected", "title"),
    [
        ("/v1/programs", {"university_id": HUGE_ID}, 422, "Validation error"),
        ("/v1/programs", {"university_id": -HUGE_ID}, 422, "Validation error"),
        (f"/v1/olympiads/{HUGE_ID}/profiles", None, 404, "Олимпиада не найдена"),
        (
            f"/v1/extra-points/universities/{HUGE_ID}",
            {"admission_year": YEAR},
            404,
            "Вуз не найден",
        ),
    ],
)
async def test_huge_id_in_query_or_path(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, object] | None,
    expected: int,
    title: str,
) -> None:
    response = await client.get(path, params=params)
    assert_problem(response, expected, title)


async def test_huge_university_id_in_score(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/extra-points/score",
        json={"university_id": HUGE_ID, "admission_year": YEAR, "claims": []},
    )
    assert_problem(response, 404, "Вуз не найден")


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("Вышка", "НИУ ВШЭ (Москва)"),
        ("бауманка", "МГТУ им. Н.Э. Баумана"),
        ("Физтех", "МФТИ"),
        ("политех", "СПбПУ Петра Великого (Политех)"),
        ("Плешка", "РЭУ им. Г.В. Плеханова"),
        ("мифи", "НИЯУ МИФИ"),
        ("Питерский универ", "СПбГУ"),
        ("спбгу", "СПбГУ"),
    ],
)
async def test_universities_search_by_nickname(
    client: httpx.AsyncClient, q: str, expected: str
) -> None:
    body = (await client.get("/v1/universities", params={"q": q})).json()
    assert expected in [item["name"] for item in body["items"]]
    assert all(item["nicknames"] is not None for item in body["items"])


async def test_universities_nicknames_listed(client: httpx.AsyncClient) -> None:
    items = (await client.get("/v1/universities")).json()["items"]
    by_name = {item["name"]: item for item in items}
    assert "вышка" in by_name["НИУ ВШЭ (Москва)"]["nicknames"]
    assert by_name["НИУ МИЭТ (Москва, Зеленоград)"]["nicknames"] == []


def test_nickname_fragments() -> None:
    assert name_fragments("Выш") == ["ВШЭ"]
    assert name_fragments("вы") == []  # короче трёх букв не угадываем
    assert name_fragments("абракадабра") == []
