"""«Предложить вуз или документ»: проверка адреса, дубли, лимит, id пользователя MAX."""

import json
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any
from urllib.parse import quote, urlencode

import httpx
import psycopg
import pytest
from olymp_api.main import create_app
from olymp_api.max_auth import sign
from olymp_api.settings import Settings
from olymp_db.session import psycopg_dsn

BOT_TOKEN = "test-bot-token"
KNOWN = "https://known-uni.example/olimpiady.pdf"


def init_data(user_id: int, *, token: str) -> str:
    params = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": user_id, "first_name": "Маша"}, ensure_ascii=False),
    }
    params["hash"] = sign(params, token)
    return urlencode(params, quote_via=quote)


def client_for(url: str, **settings: Any) -> httpx.AsyncClient:
    app = create_app(Settings(_env_file=None, database_url=url, rate_limit_requests=0, **settings))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.fixture
def db(empty_database_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        conn.execute("DELETE FROM sources")
        conn.execute("DELETE FROM universities")
        conn.execute("INSERT INTO universities (name, short_name) VALUES ('Вуз Известный', 'ВИ')")
        conn.execute(
            "INSERT INTO university_documents (university_id, title, url, checked_at)"
            " SELECT id, 'Приложение', %s, '2026-01-01' FROM universities",
            (KNOWN,),
        )
        conn.commit()
        yield conn
        conn.execute("DELETE FROM sources")
        conn.execute("DELETE FROM universities")
        conn.commit()


@pytest.fixture
async def client(empty_database_url: str, db: psycopg.Connection[Any]) -> AsyncIterator[Any]:
    async with client_for(empty_database_url, suggestion_rate_limit=0) as c:
        yield c


async def suggest(client: httpx.AsyncClient, url: str, university: str = "Вуз Известный") -> Any:
    return await client.post("/v1/suggestions", json={"url": url, "university": university})


async def test_suggestion_creates_user_job(
    client: httpx.AsyncClient, db: psycopg.Connection[Any]
) -> None:
    body = {
        "url": "https://abit.known-uni.example/olymp/page",
        "university": "вуз известный",
        "comment": "  Новые правила приёма ",
    }
    response = await client.post("/v1/suggestions", json=body)
    assert response.status_code == 201
    assert response.json() == {"status": "created"}  # ни id, ни адресов в ответе
    row = db.execute(
        """SELECT s.university, s.added_by, s.kind, j.origin, j.comment, j.status, j.max_user_id
           FROM source_jobs j JOIN sources s ON s.id = j.source_id"""
    ).fetchone()
    assert row == ("Вуз Известный", "user", "page", "user", "Новые правила приёма", "queued", None)


async def test_known_domain_and_ru_zone(client: httpx.AsyncClient) -> None:
    # сайт вуза в чужой зоне: пускаем по домену его известных документов
    assert (await suggest(client, "https://pk.known-uni.example/a.xlsx")).status_code == 201
    # любая другая зона — нет
    assert (await suggest(client, "https://other.example/a.pdf")).status_code == 422
    # .ru и .рф принимаем, вуз указан
    assert (await suggest(client, "https://новыйвуз.рф/docs/a.pdf", "Новый вуз")).status_code == 201
    assert (await suggest(client, "https://newuni.ru/docs", "Новый вуз")).status_code == 201
    # файлообменники и соцсети — не сайт вуза
    assert (await suggest(client, "https://vk.com/doc1_2.pdf")).status_code == 422
    assert (await suggest(client, "https://disk.yandex.ru/i/abc")).status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "ftp://newuni.ru/a.pdf",
        "javascript:alert(1)",
        "newuni.ru/a.pdf",
        "https://user:pass@newuni.ru/a.pdf",
        "https://newuni.ru/spisok_postupayushchih.pdf",
        "https://newuni.ru/docs/Приказ о зачислении.pdf",
    ],
)
async def test_bad_links_are_rejected(client: httpx.AsyncClient, url: str) -> None:
    response = await suggest(client, url, "Новый вуз")
    assert response.status_code == 422
    assert url not in response.text  # введённое не возвращаем


async def test_duplicates_say_exists(
    client: httpx.AsyncClient, db: psycopg.Connection[Any]
) -> None:
    assert (await suggest(client, "https://newuni.ru/docs/a.pdf", "Новый вуз")).json() == {
        "status": "created"
    }
    again = await suggest(client, "https://newuni.ru/docs/a.pdf", "Другой вуз")
    assert again.status_code == 201 and again.json() == {"status": "exists"}
    # ссылка из справочника документов вуза тоже «уже есть»
    assert (await suggest(client, KNOWN)).json() == {"status": "exists"}
    assert db.execute("SELECT count(*) FROM source_jobs").fetchone() == (1,)


async def test_remembers_max_user(empty_database_url: str, db: psycopg.Connection[Any]) -> None:
    async with client_for(empty_database_url, max_bot_token=BOT_TOKEN) as c:
        body = {"url": "https://newuni.ru/a.pdf", "university": "Новый вуз"}
        ok = await c.post(
            "/v1/suggestions",
            json=body,
            headers={"X-Max-Init-Data": init_data(4242, token=BOT_TOKEN)},
        )
        forged = await c.post(
            "/v1/suggestions",
            json={**body, "url": "https://newuni.ru/b.pdf"},
            headers={"X-Max-Init-Data": init_data(7, token="чужой")},
        )
    assert ok.status_code == forged.status_code == 201
    rows = dict(
        db.execute(
            "SELECT s.url, j.max_user_id FROM source_jobs j JOIN sources s ON s.id = j.source_id"
        ).fetchall()
    )
    assert rows == {"https://newuni.ru/a.pdf": 4242, "https://newuni.ru/b.pdf": None}


async def test_rate_limit(empty_database_url: str, db: psycopg.Connection[Any]) -> None:
    async with client_for(empty_database_url, suggestion_rate_limit=2) as c:
        codes = [
            (await suggest(c, f"https://newuni.ru/{n}.pdf", "Новый вуз")).status_code
            for n in range(3)
        ]
    assert codes == [201, 201, 429]
