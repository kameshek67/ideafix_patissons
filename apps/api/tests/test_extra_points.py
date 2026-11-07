"""Баллы за индивидуальные достижения на базе, собранной из настоящих XLSX и CSV."""

import httpx

YEAR = 2026


async def uni_by_name(client: httpx.AsyncClient, name: str) -> int:
    items = (
        await client.get("/v1/extra-points/universities", params={"admission_year": YEAR})
    ).json()["items"]
    return next(u["id"] for u in items if u["name"] == name)


async def test_universities_with_data(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/extra-points/universities", params={"admission_year": YEAR})
    assert r.status_code == 200
    names = {u["name"] for u in r.json()["items"]}
    assert {"Университет ИТМО", "НИЯУ МИФИ", "НИУ ВШЭ (Москва)"} <= names
    empty = await client.get("/v1/extra-points/universities", params={"admission_year": 2030})
    assert empty.json()["items"] == []


async def test_rules_have_sources_and_limit(client: httpx.AsyncClient) -> None:
    uid = await uni_by_name(client, "НИЯУ МИФИ")
    body = (
        await client.get(f"/v1/extra-points/universities/{uid}", params={"admission_year": YEAR})
    ).json()
    assert body["max_total"] == 10
    assert body["max_total_source"]["url"].startswith("https://")
    assert body["rules"]
    for r in body["rules"]:
        assert r["source"]["url"].startswith("https://") and r["source"]["quote"]
        assert r["source"]["page"] is not None
        assert r["review"] in {"extracted", "reviewed"}
    gto = {r["variants"][0]: r["points"] for r in body["rules"] if r["kind"] == "gto_badge"}
    assert gto == {"gold": 4, "silver": 3, "bronze": 2}  # баллы МИФИ зависят от степени знака


async def test_score_gto_depends_on_university(client: httpx.AsyncClient) -> None:
    """Один и тот же золотой знак ГТО: у вузов разные баллы и разные условия."""
    expected = {"НИЯУ МИФИ": 4, "Университет ИТМО": 2, "НИУ ВШЭ (Москва)": 2}
    for name, points in expected.items():
        uid = await uni_by_name(client, name)
        claim = {"kind": "gto_badge", "variant": "gold", "year": 2025}
        r = await client.post(
            "/v1/extra-points/score",
            json={"university_id": uid, "admission_year": YEAR, "claims": [claim]},
        )
        res = r.json()
        assert r.status_code == 200, r.text
        assert res["total"] == points, name
        assert res["awards"][0]["source"]["quote"]
        assert res["unverified"] is True  # правила ещё не сверены человеком


async def test_score_respects_year_and_degree(client: httpx.AsyncClient) -> None:
    uid = await uni_by_name(client, "Университет ИТМО")
    old = await client.post(
        "/v1/extra-points/score",
        json={
            "university_id": uid,
            "admission_year": YEAR,
            "claims": [{"kind": "gto_badge", "variant": "gold", "year": 2023}],
        },
    )
    assert old.json()["total"] == 0
    assert old.json()["skipped"][0]["reason"] == "year_not_allowed"
    hse = await uni_by_name(client, "НИУ ВШЭ (Москва)")
    silver = await client.post(
        "/v1/extra-points/score",
        json={
            "university_id": hse,
            "admission_year": YEAR,
            "claims": [{"kind": "gto_badge", "variant": "silver", "year": 2026}],
        },
    )
    assert silver.json()["total"] == 0  # ВШЭ засчитывает только золотой знак
    assert silver.json()["unmatched"][0]["variant"] == "silver"


async def test_score_never_exceeds_limit(client: httpx.AsyncClient) -> None:
    uid = await uni_by_name(client, "НИУ ВШЭ (Москва)")
    claims = [
        {"kind": "honors_document"},
        {"kind": "abilimpics", "year": 2025},
        {"kind": "olympiad_final", "year": 2025},
    ]
    res = (
        await client.post(
            "/v1/extra-points/score",
            json={"university_id": uid, "admission_year": YEAR, "claims": claims},
        )
    ).json()
    assert res["raw_total"] > 10 and res["total"] == 10 and res["capped"] is True


async def test_score_by_rule_id_awards_only_chosen_rule(client: httpx.AsyncClient) -> None:
    uid = await uni_by_name(client, "НИЯУ МИФИ")
    rules = (
        await client.get(f"/v1/extra-points/universities/{uid}", params={"admission_year": YEAR})
    ).json()["rules"]
    pick = next(r for r in rules if r["kind"] == "military")
    claim = {"kind": "military", "rule_id": pick["id"]}
    res = (
        await client.post(
            "/v1/extra-points/score",
            json={"university_id": uid, "admission_year": YEAR, "claims": [claim]},
        )
    ).json()
    assert [a["rule_id"] for a in res["awards"]] == [pick["id"]]


async def test_no_data_and_unknown_university(client: httpx.AsyncClient) -> None:
    unis = (await client.get("/v1/universities")).json()["items"]
    with_data = {
        u["id"]
        for u in (
            await client.get("/v1/extra-points/universities", params={"admission_year": YEAR})
        ).json()["items"]
    }
    other = next(u["id"] for u in unis if u["id"] not in with_data)
    res = (
        await client.post(
            "/v1/extra-points/score",
            json={
                "university_id": other,
                "admission_year": YEAR,
                "claims": [{"kind": "gto_badge"}],
            },
        )
    ).json()
    assert res["status"] == "no_data" and res["total"] == 0 and res["max_total"] is None
    missing = await client.get(
        "/v1/extra-points/universities/999999", params={"admission_year": YEAR}
    )
    assert missing.status_code == 404
    bad = await client.post(
        "/v1/extra-points/score",
        json={"university_id": 1, "admission_year": YEAR, "claims": [{"kind": "wat"}]},
    )
    assert bad.status_code == 422
