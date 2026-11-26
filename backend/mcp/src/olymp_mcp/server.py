"""MCP-сервер: инструменты читают только публичное HTTP API «Олимпа»."""

from collections.abc import Callable

import httpx
from mcp.server.fastmcp import FastMCP

from . import tools
from .client import Json, OlympClient

ClientFactory = Callable[[], OlympClient]


def create_server(
    *, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> FastMCP:
    def factory() -> OlympClient:
        return OlympClient(base_url, transport=transport)

    server = FastMCP(
        "olymp",
        instructions="Данные «Олимпа»: олимпиады, вузы, направления и льготы БВИ / 100 баллов.",
    )

    @server.tool(description="Поиск олимпиад по названию или сокращению.")
    async def search_olympiads(query: str) -> Json:
        async with factory() as client:
            return await tools.search_olympiads(query, client)

    @server.tool(description="Вузы и льготы по олимпиаде; можно уточнить профиль и тип льготы.")
    async def benefits_by_olympiad(
        olympiad_id: int,
        profile_id: int | None = None,
        benefit_type: str | None = None,
    ) -> Json:
        async with factory() as client:
            return await tools.benefits_by_olympiad(olympiad_id, profile_id, benefit_type, client)

    @server.tool(description="Вузы и направления по названию, профилю или коду.")
    async def university_programs(query: str) -> Json:
        async with factory() as client:
            return await tools.university_programs(query, client)

    @server.tool(description="Олимпиады и типы льгот для выбранного направления.")
    async def olympiads_for_program(program_id: int) -> Json:
        async with factory() as client:
            return await tools.olympiads_for_program(program_id, client)

    @server.tool(description="Где дипломы дают БВИ или 100 баллов.")
    async def match_diplomas(diplomas: list[str]) -> Json:
        async with factory() as client:
            return await tools.match_diplomas(diplomas, client)

    return server


mcp = create_server()


def main() -> None:
    mcp.run(transport="stdio")
