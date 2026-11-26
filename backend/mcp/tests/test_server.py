import httpx
import pytest
from olymp_mcp.client import OlympApiError, OlympClient
from olymp_mcp.server import create_server

EXPECTED_TOOLS = {
    "search_olympiads",
    "benefits_by_olympiad",
    "university_programs",
    "olympiads_for_program",
    "match_diplomas",
}


def transport(calls: list[httpx.Request], replies: dict[str, object]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path not in replies:
            return httpx.Response(404, json={"detail": "нет"}, request=request)
        return httpx.Response(200, json=replies[request.url.path], request=request)

    return httpx.MockTransport(handle)


async def call(server: object, name: str, arguments: dict[str, object]) -> dict[str, object]:
    result = await server.call_tool(name, arguments)  # type: ignore[attr-defined]
    return result[1]


async def test_server_registers_five_tools() -> None:
    server = create_server()
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    assert all(tool.description for tool in tools)


async def test_search_olympiads_uses_query_and_trims_response() -> None:
    calls: list[httpx.Request] = []
    server = create_server(
        base_url="https://olymp.test/api",
        transport=transport(
            calls,
            {
                "/api/v1/olympiads": {
                    "count": 1,
                    "items": [
                        {
                            "id": 7,
                            "short_name": "Вышка",
                            "canonical_name": "Высшая проба",
                            "kind": "олимпиада",
                            "bvi_count": 3,
                            "sto_count": 5,
                            "uni_count": 12,
                            "mentions": 40,
                            "rank": 1,
                        }
                    ],
                }
            },
        ),
    )
    data = await call(server, "search_olympiads", {"query": "вышка"})

    assert calls[0].url.path == "/api/v1/olympiads"
    assert calls[0].url.params["q"] == "вышка"
    assert data == {
        "items": [
            {
                "id": 7,
                "name": "Вышка",
                "kind": "олимпиада",
                "bvi": 3,
                "sto": 5,
                "universities": 12,
            }
        ],
        "sources": [],
    }


async def test_benefits_by_olympiad_requests_summary() -> None:
    calls: list[httpx.Request] = []
    server = create_server(
        base_url="https://olymp.test/api",
        transport=transport(
            calls,
            {
                "/api/v1/search/by-olympiad": {
                    "query": "олимпиада 7",
                    "matched_olympiads": [{"id": 7, "short_name": "Вышка"}],
                    "results": [
                        {
                            "university": {
                                "id": 1,
                                "name": "МГУ",
                                "short_name": "мгу",
                                "docs_url": "https://uni.example/docs.pdf",
                                "docs_title": "Правила приёма",
                            },
                            "programs_total": 4,
                            "bvi": 2,
                            "sto": 1,
                            "other": 0,
                            "programs": [],
                        }
                    ],
                    "card": {"source_url": "https://olymp.example/about"},
                }
            },
        ),
    )
    data = await call(
        server, "benefits_by_olympiad", {"olympiad_id": 7, "profile_id": 3, "benefit_type": "БВИ"}
    )

    params = calls[0].url.params
    assert calls[0].url.path == "/api/v1/search/by-olympiad"
    assert params["olympiad_id"] == "7"
    assert params["profile_id"] == "3"
    assert params["benefit_type"] == "БВИ"
    assert params["view"] == "summary"
    assert params["q"]
    assert data["universities"] == [
        {"id": 1, "name": "мгу", "programs": 4, "bvi": 2, "sto": 1, "other": 0}
    ]
    assert data["sources"] == [
        {
            "url": "https://uni.example/docs.pdf",
            "title": "Правила приёма",
            "university": "мгу",
        }
    ]
    assert "card" not in data
    assert "results" not in data


async def test_university_programs_calls_both_endpoints() -> None:
    calls: list[httpx.Request] = []
    server = create_server(
        base_url="https://olymp.test/api",
        transport=transport(
            calls,
            {
                "/api/v1/universities": {
                    "count": 1,
                    "items": [
                        {
                            "id": 1,
                            "name": "МГУ",
                            "short_name": "мгу",
                            "programs": 2,
                            "bvi": 3,
                            "sto": 1,
                        }
                    ],
                },
                "/api/v1/programs": {
                    "count": 1,
                    "items": [
                        {
                            "id": 11,
                            "university_id": 1,
                            "university": "МГУ",
                            "faculty_or_direction": "Математика",
                            "profile_name": "Математика",
                            "code": "01.03.01",
                            "source_url": "https://uni.example/program.pdf",
                            "source_title": "Направления",
                        }
                    ],
                },
            },
        ),
    )
    data = await call(server, "university_programs", {"query": "математика"})

    assert [request.url.path for request in calls] == [
        "/api/v1/universities",
        "/api/v1/programs",
    ]
    assert all(request.url.params["q"] == "математика" for request in calls)
    assert data["programs"] == [
        {
            "id": 11,
            "university": "МГУ",
            "name": "Математика",
            "code": "01.03.01",
            "profile": "Математика",
        }
    ]
    assert data["sources"] == [
        {"url": "https://uni.example/program.pdf", "title": "Направления", "university": "МГУ"}
    ]


async def test_olympiads_for_program_keeps_types_and_sources() -> None:
    calls: list[httpx.Request] = []
    server = create_server(
        base_url="https://olymp.test/api",
        transport=transport(
            calls,
            {
                "/api/v1/search/by-program": {
                    "program": {
                        "id": 11,
                        "faculty_or_direction": "Математика",
                        "profile_name": "Математика",
                        "code": "01.03.01",
                    },
                    "university": {
                        "id": 1,
                        "name": "МГУ",
                        "short_name": "мгу",
                        "docs_url": "https://uni.example/docs",
                    },
                    "groups": [],
                    "notes": [],
                    "olympiads": [
                        {
                            "id": 7,
                            "short_name": "Вышка",
                            "types": ["БВИ", "100 баллов"],
                            "count": 2,
                        }
                    ],
                    "total_benefits": 2,
                    "sources": [
                        {
                            "title": "Приёмная комиссия",
                            "url": "https://uni.example/docs",
                            "kind": "page",
                            "types": [],
                        }
                    ],
                }
            },
        ),
    )
    data = await call(server, "olympiads_for_program", {"program_id": 11})

    assert calls[0].url.path == "/api/v1/search/by-program"
    assert calls[0].url.params["program_id"] == "11"
    assert data["program"] == {
        "id": 11,
        "name": "Математика",
        "code": "01.03.01",
        "university": "мгу",
    }
    assert data["olympiads"] == [
        {"id": 7, "name": "Вышка", "types": ["БВИ", "100 баллов"], "count": 2}
    ]
    assert data["sources"] == [
        {
            "url": "https://uni.example/docs",
            "title": "Приёмная комиссия",
            "university": "мгу",
        }
    ]
    assert "groups" not in data


async def test_match_diplomas_sends_repeated_diploma_param() -> None:
    calls: list[httpx.Request] = []
    server = create_server(
        base_url="https://olymp.test/api",
        transport=transport(
            calls,
            {
                "/api/v1/achievements/match": {
                    "diplomas": [
                        {
                            "spec": "высшаяпроба.математика.w.11.2025",
                            "found": True,
                            "olympiad": {"id": 7, "short_name": "Вышка"},
                            "profile": {"id": 3, "name": "Математика"},
                            "role": "w",
                            "grade": 11,
                            "year": 2025,
                        }
                    ],
                    "results": [
                        {
                            "university": {
                                "id": 1,
                                "name": "МГУ",
                                "short_name": "мгу",
                                "docs_url": "https://uni.example/docs.pdf",
                            },
                            "bvi": 2,
                            "sto": 0,
                            "other": 1,
                        }
                    ],
                    "totals": {"universities": 1, "programs": 3, "bvi": 2, "sto": 0, "other": 1},
                    "rows": [
                        {
                            "benefit": {
                                "source_url": "https://uni.example/rules.pdf",
                                "source_title": "Правила",
                            }
                        }
                    ],
                }
            },
        ),
    )
    data = await call(
        server,
        "match_diplomas",
        {"diplomas": ["высшаяпроба.математика.w.11.2025", "нто.p.10.2025"]},
    )

    assert calls[0].url.path == "/api/v1/achievements/match"
    assert calls[0].url.params.get_list("diploma") == [
        "высшаяпроба.математика.w.11.2025",
        "нто.p.10.2025",
    ]
    assert data["diplomas"][0]["olympiad"] == "Вышка"
    assert data["universities"] == [{"id": 1, "name": "мгу", "bvi": 2, "sto": 0, "other": 1}]
    assert data["totals"]["programs"] == 3
    assert {source["url"] for source in data["sources"]} == {
        "https://uni.example/docs.pdf",
        "https://uni.example/rules.pdf",
    }
    assert "rows" not in data


async def test_api_errors_are_readable() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "не готово"}, request=request)

    with pytest.raises(OlympApiError, match="HTTP 503"):
        async with OlympClient(
            "https://olymp.test/api", transport=httpx.MockTransport(handle)
        ) as client:
            await client.get("v1/olympiads")


async def test_default_api_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLYMP_API_URL", raising=False)
    calls: list[httpx.Request] = []
    client = OlympClient(
        transport=httpx.MockTransport(
            lambda request: (calls.append(request), httpx.Response(200, json={}))[1]
        )
    )
    await client.get("v1/olympiads")
    assert str(calls[0].url) == "https://ideafix.patissons.tech/api/v1/olympiads"
