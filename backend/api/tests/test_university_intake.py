"""Набор олимпиадников в карточке и списке вуза (сводная панель «Мониторинг эффективности вузов»)."""

import httpx
import psycopg
from olymp_db.session import psycopg_dsn


async def university(client: httpx.AsyncClient, name: str) -> dict:
    items = (await client.get("/v1/universities", params={"region": "Все"})).json()["items"]
    return next(u for u in items if u["name"] == name)


async def test_list_has_latest_year_with_source(client: httpx.AsyncClient) -> None:
    item = await university(client, "МФТИ")
    assert item["intake"] == {
        "year": 2024,
        "olympiad_students": 624,
        "olympiad_share": 12.45,
        "avg_score_budget": 98.67,
        "source": "Мониторинг эффективности вузов",
    }


async def test_university_outside_the_panel_has_no_intake(client: httpx.AsyncClient) -> None:
    # АНО ВО: в панели только государственные вузы
    item = await university(client, "Университет Иннополис (АНО ВО)")
    assert item["intake"] is None


async def test_empty_olympiad_count_is_null_not_zero(client: httpx.AsyncClient) -> None:
    # филиалы МИФИ: олимпиадников в панели нет, средний балл есть
    item = await university(client, "НИЯУ МИФИ — филиалы")
    assert item["intake"]["olympiad_students"] is None
    assert item["intake"]["avg_score_budget"] > 0


async def test_card_of_program_has_intake(
    client: httpx.AsyncClient, built_database_url: str
) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        program_id = conn.execute(
            "SELECT p.id FROM programs p JOIN universities u ON u.id = p.university_id"
            " WHERE u.name = 'МФТИ' ORDER BY p.id LIMIT 1"
        ).fetchone()[0]
    data = (await client.get("/v1/search/by-program", params={"program_id": program_id})).json()
    assert data["university"]["intake"]["olympiad_students"] == 624
