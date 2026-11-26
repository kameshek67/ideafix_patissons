"""Справочный поиск: функция по таблице passages и инструмент помощника в цикле на подставной модели."""

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
import psycopg
import pytest
from olymp_api.db import make_engine
from olymp_api.llm import TextDelta, ToolCall, ToolCalls
from olymp_api.llm.fake import FakeProvider
from olymp_api.main import create_app
from olymp_api.modules.assistant import prompt
from olymp_api.modules.assistant.references import MAX_LIMIT, search_passages
from olymp_api.modules.assistant.schemas import ChatMessage
from olymp_api.modules.assistant.service import collect_facts
from olymp_api.modules.assistant.tools import TOOLS, ToolContext, ToolResult, run_tool
from olymp_api.settings import Settings
from olymp_db.session import psycopg_dsn
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

ROWS = [
    (
        "olympiad_card",
        "Олимпиада Альфа",
        "https://alpha.example",
        None,
        0,
        "Олимпиада Альфа проходит в три этапа: отборочный, заочный и очный финал в Москве.",
    ),
    (
        "admission_rule",
        "Федеральный закон об образовании",
        "https://law.example",
        None,
        0,
        "Победители и призёры олимпиад школьников принимаются без вступительных испытаний.",
    ),
    (
        "university_document",
        "МАИ: Правила приёма",
        "https://mai.example/rules.pdf",
        7,
        0,
        "Документы подаются до 25 июля. Индивидуальные достижения учитываются отдельно.",
    ),
    (
        "university_document",
        "МАИ: Правила приёма",
        "https://mai.example/rules.pdf",
        7,
        1,
        "Документы подаются до конца июля, конкурсные списки публикуются на сайте.",
    ),
    (
        "university_document",
        "МАИ: Правила приёма",
        "https://mai.example/rules.pdf",
        8,
        0,
        "Документы принимаются в приёмной комиссии, вторая страница правил.",
    ),
]


@pytest.fixture
def passages(empty_database_url: str) -> Any:
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        conn.execute("DELETE FROM passages")
        for source_type, title, url, page, chunk, body in ROWS:
            conn.execute(
                """INSERT INTO passages (source_type, title, url, page, chunk, body, document)
                   VALUES (%s,%s,%s,%s,%s,%s, to_tsvector('russian', %s))""",
                (source_type, title, url, page, chunk, body, f"{title}. {body}"),
            )
        conn.commit()
    yield empty_database_url
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        conn.execute("DELETE FROM passages")
        conn.commit()


@pytest.fixture
async def session(passages: str) -> AsyncIterator[AsyncSession]:
    engine = make_engine(Settings(_env_file=None, database_url=passages))
    assert engine is not None
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


async def test_search_finds_by_word_forms(session: AsyncSession) -> None:
    found = await search_passages(session, "как проходят этапы олимпиады Альфа")
    assert found[0].title == "Олимпиада Альфа"
    assert found[0].url == "https://alpha.example"


async def test_search_keeps_page_and_limits_one_source(session: AsyncSession) -> None:
    found = await search_passages(session, "документы подаются июль", limit=5)
    mai = [r for r in found if r.url == "https://mai.example/rules.pdf"]
    assert {r.page for r in mai} <= {7, 8}
    assert len(mai) <= 2  # куски одного документа не забивают выдачу
    assert (await search_passages(session, "закон", limit=1))[0].label == "правила приёма и закон"


async def test_search_nothing_and_empty(session: AsyncSession) -> None:
    assert await search_passages(session, "квантовая хромодинамика") == []
    assert await search_passages(session, "   ") == []
    assert len(await search_passages(session, "олимпиад", limit=99)) <= MAX_LIMIT


async def test_tool_returns_source_and_page(session: AsyncSession) -> None:
    ctx = ToolContext(session=session, diplomas=[])
    result = await run_tool(
        "search_references", json.dumps({"query": "документы подаются до июля"}), ctx
    )
    payload = json.loads(result.content)
    assert payload["fragments"][0]["source"] == "МАИ: Правила приёма"
    assert payload["fragments"][0]["page"] == 7
    assert result.reference
    assert result.sources[0]["url"] == "https://mai.example/rules.pdf"
    assert "стр. 7" in result.sources[0]["title"]
    empty = await run_tool("search_references", json.dumps({"query": "бозон хиггса"}), ctx)
    assert json.loads(empty.content)["fragments"] == []
    bad = await run_tool("search_references", "{}", ctx)
    assert "error" in json.loads(bad.content)


def test_reference_text_is_not_a_confirmed_fact() -> None:
    reference = ToolResult(
        json.dumps({"fragments": [{"text": "порог 777 баллов"}]}), reference=True
    )
    data = ToolResult(json.dumps({"rows": [{"text": "проходной 555"}]}))
    facts = collect_facts([reference, data], [ChatMessage(role="user", content="привет")], None)
    assert 555 in facts.numbers
    assert 777 not in facts.numbers


def test_prompt_separates_facts_from_references() -> None:
    assert any(t["function"]["name"] == "search_references" for t in TOOLS)
    assert "search_references" in prompt.SYSTEM_PROMPT
    assert "страниц" in prompt.SYSTEM_PROMPT
    assert int(prompt.PROMPT_VERSION) >= 7


async def test_assistant_loop_uses_references(passages: str) -> None:
    app = create_app(Settings(_env_file=None, database_url=passages, rate_limit_requests=0))
    rounds: Sequence[Sequence[Any]] = [
        [ToolCalls((ToolCall("c1", "search_references", '{"query":"этапы олимпиады Альфа"}'),))],
        [TextDelta("Олимпиада Альфа проходит в три этапа. Источник: Олимпиада Альфа.")],
    ]
    fake = FakeProvider(rounds)
    app.state.llm = fake
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/assistant/chat",
            json={"messages": [{"role": "user", "content": "Как проходит Альфа?"}]},
        )
    await app.state.engine.dispose()
    assert response.status_code == 200, response.text
    tool_messages = [m for m in fake.requests[-1]["messages"] if m["role"] == "tool"]
    assert "Олимпиада Альфа" in json.loads(tool_messages[0]["content"])["fragments"][0]["source"]
    assert "https://alpha.example" in response.text


async def test_built_database_answers_reference_questions(built_database_url: str) -> None:
    engine = make_engine(Settings(_env_file=None, database_url=built_database_url))
    assert engine is not None
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        law = await search_passages(db, "что такое БВИ без вступительных испытаний")
        cards = await search_passages(db, "как проходит национальная технологическая олимпиада")
    await engine.dispose()
    assert any(r.source_type == "admission_rule" and r.url.startswith("https://") for r in law)
    assert any(r.source_type == "olympiad_card" for r in cards)
