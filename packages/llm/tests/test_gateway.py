import json

import httpx
import pytest
from olymp_llm import (
    LLMError,
    OpenAICompatibleProvider,
    TextDelta,
    ToolCall,
    ToolCalls,
    complete,
    provider_from_env,
)
from olymp_llm import gateway as gateway_module
from olymp_llm.fake import FakeProvider

MESSAGES = [{"role": "user", "content": "привет"}]


def sse(*chunks: object) -> bytes:
    lines = [": OPENROUTER PROCESSING\n\n"]
    lines += [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


def text_chunk(text: str) -> dict[str, object]:
    return {"choices": [{"delta": {"content": text}}]}


def provider(handler: httpx.MockTransport, **kwargs: object) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        "https://openrouter.ai/api/v1", "key", "main", transport=handler, **kwargs
    )


async def collect(p: OpenAICompatibleProvider) -> list[object]:
    return [event async for event in p.stream(MESSAGES, [])]


@pytest.fixture(autouse=True)
def no_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway_module, "RETRY_DELAY", 0)


async def test_streams_text_and_denies_data_collection() -> None:
    seen: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer key"
        return httpx.Response(200, content=sse(text_chunk("При"), text_chunk("вет")))

    events = await collect(provider(httpx.MockTransport(handle)))
    assert events == [TextDelta("При"), TextDelta("вет")]
    assert seen[0]["provider"] == {"data_collection": "deny"}
    assert seen[0]["stream"] is True
    assert "tools" not in seen[0]
    assert "temperature" not in seen[0]


async def test_sends_generation_parameters() -> None:
    seen: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=sse(text_chunk("ok")))

    await collect(provider(httpx.MockTransport(handle), temperature=0.2, top_p=0.9))
    assert seen[0]["temperature"] == 0.2
    assert seen[0]["top_p"] == 0.9


async def test_other_servers_do_not_get_openrouter_field() -> None:
    seen: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=sse(text_chunk("ok")))

    p = OpenAICompatibleProvider(
        "http://localhost:11434/v1", "key", "main", transport=httpx.MockTransport(handle)
    )
    await collect(p)
    assert "provider" not in seen[0]


async def test_assembles_tool_call_from_parts() -> None:
    parts = [
        {"index": 0, "id": "c1", "function": {"name": "find_profiles", "arguments": '{"key'}},
        {"index": 0, "function": {"arguments": 'words": ["робот"]}'}},
    ]
    body = sse(*[{"choices": [{"delta": {"tool_calls": [part]}}]} for part in parts])
    p = provider(httpx.MockTransport(lambda _: httpx.Response(200, content=body)))
    assert await collect(p) == [
        ToolCalls((ToolCall("c1", "find_profiles", '{"keywords": ["робот"]}'),))
    ]


async def test_falls_back_to_second_model() -> None:
    models: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        models.append(model)
        if model == "main":
            return httpx.Response(429)
        return httpx.Response(200, content=sse(text_chunk("запас")))

    events = await collect(provider(httpx.MockTransport(handle), fallback_model="spare"))
    assert models == ["main", "main", "spare"]
    assert events == [TextDelta("запас")]


async def test_error_inside_stream_is_retried() -> None:
    answers = [sse({"error": {"code": 502}}), sse(text_chunk("ок"))]
    p = provider(httpx.MockTransport(lambda _: httpx.Response(200, content=answers.pop(0))))
    assert await collect(p) == [TextDelta("ок")]


async def test_all_models_failed() -> None:
    p = provider(httpx.MockTransport(lambda _: httpx.Response(503)))
    with pytest.raises(LLMError):
        await collect(p)


async def test_bad_key_is_not_retried() -> None:
    calls: list[int] = []

    def handle(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401)

    with pytest.raises(LLMError):
        await collect(provider(httpx.MockTransport(handle), fallback_model="spare"))
    assert len(calls) == 1


async def test_no_retry_after_first_event() -> None:
    calls: list[int] = []

    def handle(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, content=sse(text_chunk("начало"), {"error": {"code": 502}}))

    events: list[object] = []
    with pytest.raises(LLMError):
        async for event in provider(httpx.MockTransport(handle)).stream(MESSAGES, []):
            events.append(event)
    assert events == [TextDelta("начало")]
    assert len(calls) == 1


async def test_temperature_is_sent_only_when_set() -> None:
    seen: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=sse(text_chunk("ok")))

    await collect(provider(httpx.MockTransport(handle)))
    await collect(provider(httpx.MockTransport(handle), temperature=0))
    assert "temperature" not in seen[0]
    assert seen[1]["temperature"] == 0


async def test_complete_joins_text() -> None:
    fake = FakeProvider([[TextDelta('{"a"'), TextDelta(": 1}")]])
    assert await complete(fake, MESSAGES) == '{"a": 1}'
    assert fake.requests[0]["tools"] == []


ENV = {"OLYMP_LLM_BASE_URL": "https://x/v1", "OLYMP_LLM_API_KEY": "k", "OLYMP_LLM_MODEL": "chat"}


@pytest.mark.parametrize(
    "env",
    [
        {},
        {**ENV, "OLYMP_LLM_API_KEY": ""},
        {**ENV, "OLYMP_LLM_MODEL": ""},
        {**ENV, "OLYMP_LLM_ENABLED": "false"},
    ],
)
def test_provider_from_env_is_off(env: dict[str, str]) -> None:
    assert provider_from_env(env) is None


def test_provider_from_env_picks_parser_model() -> None:
    chat = provider_from_env(ENV)
    parser = provider_from_env(
        {**ENV, "OLYMP_PARSER_MODEL": "parser"}, model_var="OLYMP_PARSER_MODEL"
    )
    fallback = provider_from_env(ENV, model_var="OLYMP_PARSER_MODEL")
    assert chat is not None and chat.model_label == "chat"
    assert parser is not None and parser.model_label == "parser"
    assert fallback is not None and fallback.model_label == "chat"


async def test_fake_provider_plays_rounds() -> None:
    fake = FakeProvider([[TextDelta("раз")], [RuntimeError("сбой")]])
    assert [e async for e in fake.stream(MESSAGES, [])] == [TextDelta("раз")]
    with pytest.raises(RuntimeError):
        [e async for e in fake.stream(MESSAGES, [])]
    assert len(fake.requests) == 2
