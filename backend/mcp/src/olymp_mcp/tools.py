"""Консольные инструменты: тонкие вызовы публичного API и компактная выдача."""

from . import format as fmt
from .client import Json, OlympClient, Params, ParamValue


async def _fetch(client: OlympClient | None, path: str, params: Params) -> Json:
    if client is not None:
        return await client.get(path, params)
    async with OlympClient() as own:
        return await own.get(path, params)


async def search_olympiads(query: str, client: OlympClient | None = None) -> Json:
    data = await _fetch(client, "v1/olympiads", [("q", query)])
    return fmt.olympiads(data)


async def benefits_by_olympiad(
    olympiad_id: int,
    profile_id: int | None = None,
    benefit_type: str | None = None,
    client: OlympClient | None = None,
) -> Json:
    params: list[tuple[str, ParamValue]] = [
        ("q", f"олимпиада {olympiad_id}"),
        ("olympiad_id", olympiad_id),
        ("view", "summary"),
    ]
    if profile_id is not None:
        params.append(("profile_id", profile_id))
    if benefit_type:
        params.append(("benefit_type", benefit_type))
    data = await _fetch(client, "v1/search/by-olympiad", params)
    return fmt.benefits_by_olympiad(data)


async def university_programs(query: str, client: OlympClient | None = None) -> Json:
    universities = await _fetch(client, "v1/universities", [("q", query)])
    programs = await _fetch(client, "v1/programs", [("q", query), ("limit", 50)])
    return fmt.university_programs(universities, programs)


async def olympiads_for_program(program_id: int, client: OlympClient | None = None) -> Json:
    data = await _fetch(client, "v1/search/by-program", [("program_id", program_id)])
    return fmt.olympiads_for_program(data)


async def match_diplomas(diplomas: list[str], client: OlympClient | None = None) -> Json:
    if not diplomas:
        raise ValueError("Нужен хотя бы один диплом")
    data = await _fetch(client, "v1/achievements/match", [("diploma", d) for d in diplomas])
    return fmt.match_diplomas(data)
