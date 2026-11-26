"""«Хочу в вуз»: рейтинг олимпиад под цель из нескольких направлений."""

import httpx


async def program_ids(client: httpx.AsyncClient, university: str, code: str) -> int:
    uni = (await client.get("/v1/universities", params={"q": university})).json()["items"][0]
    params = {"university_id": uni["id"], "q": code}
    return (await client.get("/v1/programs", params=params)).json()["items"][0]["id"]


async def test_goal_single_program(client: httpx.AsyncClient) -> None:
    pid = await program_ids(client, "НИУ ВШЭ (Москва)", "01.03.02")
    data = (await client.get("/v1/goals/olympiads", params={"program_id": pid})).json()
    assert [p["id"] for p in data["programs"]] == [pid]
    items = data["items"]
    assert items
    for item in items:
        assert item["bvi_programs"] or item["hundred_programs"]
        assert set(item["bvi_programs"] + item["hundred_programs"]) == {pid}
        assert item["who"] in ("winners", "winners_prizes", "team")
    # вне перечня 2026/27 — только в конце
    flags = [i["in_list_2026_27"] for i in items]
    assert flags == sorted(flags, reverse=True)
    # БВИ раньше 100 баллов среди пар из перечня
    inside = [i for i in items if i["in_list_2026_27"]]
    assert [bool(i["bvi_programs"]) for i in inside] == sorted(
        (bool(i["bvi_programs"]) for i in inside), reverse=True
    )


async def test_goal_several_programs_cover_more_first(client: httpx.AsyncClient) -> None:
    first = await program_ids(client, "НИУ ВШЭ (Москва)", "01.03.02")
    second = await program_ids(client, "НИУ ВШЭ (Москва)", "09.03.01")
    data = (
        await client.get(
            "/v1/goals/olympiads", params=[("program_id", first), ("program_id", second)]
        )
    ).json()
    assert [p["id"] for p in data["programs"]] == [first, second]
    covered = [
        len(i["bvi_programs"]) + len(i["hundred_programs"])
        for i in data["items"]
        if i["in_list_2026_27"]
    ]
    assert covered == sorted(covered, reverse=True)
    assert covered[0] == 2


async def test_goal_validation_and_not_found(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/goals/olympiads")).status_code == 422
    too_many = [("program_id", i) for i in range(1, 5)]
    assert (await client.get("/v1/goals/olympiads", params=too_many)).status_code == 422
    missing = await client.get("/v1/goals/olympiads", params={"program_id": 10**9})
    assert missing.status_code == 404
    assert missing.json()["title"] == "Направление не найдено"
