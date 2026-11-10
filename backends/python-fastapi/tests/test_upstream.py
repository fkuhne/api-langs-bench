"""The upstream client keeps the contract's rules (contract/README.md#the-upstream), against
answers shaped as llama.cpp's (docs/fake-server.md#what-llamacpp-sends)."""

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx2
import pytest

from app.errors import ServiceError
from app.llm.factory import create_llm_client
from app.llm.port import ChatMessage, ContentDelta, ReasoningDelta, StreamEnd, StreamPart, Usage
from app.settings import Settings
from app.upstream.client import OpenAICompatibleClient
from app.upstream.errors import reason

pytestmark = pytest.mark.anyio

QUESTION = [ChatMessage(role="user", content="Hi")]
USAGE = {"completion_tokens": 2, "prompt_tokens": 1, "total_tokens": 3}
Handler = Callable[[httpx2.Request], httpx2.Response]


def upstream(handler: Handler, **settings: Any) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(Settings(**settings), httpx2.MockTransport(handler))


def chunk(delta: dict[str, Any] | None = None, **fields: Any) -> str:
    """One chunk of a stream, as a `data:` line. Without a delta it has no choices."""
    choices = [] if delta is None else [{"finish_reason": None, "index": 0, "delta": delta}]
    body = {"choices": choices, "model": "fake-server", **fields}
    return f"data: {json.dumps(body)}\n\n"


def finish(reason: str) -> str:
    choices = [{"finish_reason": reason, "index": 0, "delta": {}}]
    return f"data: {json.dumps({'choices': choices, 'model': 'fake-server'})}\n\n"


STREAM = (
    chunk({"role": "assistant", "content": None})
    + chunk({"reasoning_content": "Hm"})
    + chunk({"content": "A"})
    + chunk({"content": " backend"})
    + finish("stop")
    + chunk(usage=USAGE)
    + "data: [DONE]\n\n"
)


def streams(body: str, status: int = 200) -> Handler:
    return lambda _request: httpx2.Response(status, content=body.encode())


async def parts(client: OpenAICompatibleClient, **parameters: Any) -> list[StreamPart]:
    return [part async for part in client.stream(QUESTION, parameters)]


def whole(**message: Any) -> dict[str, Any]:
    return {
        "choices": [{"finish_reason": "length", "index": 0, "message": message}],
        "model": "fake-server",
        "usage": USAGE | {"prompt_tokens_details": {"cached_tokens": 0}},
    }


async def test_a_whole_answer_is_asked_for_and_read() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        message = {"role": "assistant", "content": "A backend", "reasoning_content": "Hm"}
        return httpx2.Response(200, json=whole(**message))

    client = upstream(handler, llm_base_url="http://upstream:8080/v1/", llm_api_key="secret")

    completion = await client.complete(QUESTION, {"max_tokens": 5, "seed": 1.5})

    assert str(sent[0].url) == "http://upstream:8080/v1/chat/completions"
    assert sent[0].headers["authorization"] == "Bearer secret"
    assert json.loads(sent[0].content) == {
        "max_tokens": 5,
        "seed": 1.5,
        "model": "local",
        "messages": [{"role": "user", "content": "Hi"}],
    }
    assert completion.model_dump() == {
        "content": "A backend",
        "reasoning": "Hm",
        "model": "fake-server",
        "finish_reason": "length",
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }


async def test_a_whole_answer_with_little_in_it() -> None:
    body = {"choices": [{"message": {"role": "assistant", "content": None}}]}
    client = upstream(lambda _request: httpx2.Response(200, json=body), llm_model="mine")

    completion = await client.complete(QUESTION, {})

    assert completion.model_dump() == {
        "content": "",
        "reasoning": None,
        "model": "mine",
        "finish_reason": None,
        "usage": None,
    }


async def test_a_stream_is_one_part_for_each_piece_then_the_end() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, content=STREAM.encode())

    got = await parts(upstream(handler), max_tokens=2)

    body = json.loads(sent[0].content)
    assert (body["stream"], body["stream_options"]) == (True, {"include_usage": True})
    assert (body["max_tokens"], body["model"]) == (2, "local")
    assert got == [
        ReasoningDelta(text="Hm"),
        ContentDelta(text="A"),
        ContentDelta(text=" backend"),
        StreamEnd(
            model="fake-server",
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        ),
    ]


async def test_a_stream_is_read_as_other_servers_write_it() -> None:
    # Ollama's name for the reasoning; a comment; no space after the colon; a chunk with both
    # texts; an empty text; a delta that isn't an object; and no [DONE] before the end.
    body = (
        ": ping\n\n"
        + chunk({"reasoning": "Hm", "content": "A"}).replace("data: ", "data:")
        + chunk({"content": ""})
        + 'data: {"choices":[{"delta":null}]}\n\n'
        + "event: other\n\n"
    )

    got = await parts(upstream(streams(body), llm_model="mine"))

    assert got == [
        ReasoningDelta(text="Hm"),
        ContentDelta(text="A"),
        StreamEnd(model="fake-server", finish_reason=None, usage=None),
    ]


@pytest.mark.parametrize("usage", ["many", {"prompt_tokens": 1}, USAGE | {"total_tokens": True}])
async def test_a_usage_without_its_three_counts_is_none(usage: Any) -> None:
    *_, end = await parts(upstream(streams(chunk({"content": "A"}) + chunk(usage=usage))))

    assert end == StreamEnd(model="fake-server", finish_reason=None, usage=None)


async def test_what_follows_done_isnt_read() -> None:
    got = await parts(upstream(streams(STREAM + chunk({"content": "late"}))))

    assert ContentDelta(text="late") not in got


@pytest.mark.parametrize(
    ("status", "answered", "detail"),
    [
        (429, 429, "The LLM endpoint is rate-limiting requests."),
        (400, 502, "The LLM endpoint refused the request with status 400: no"),
        (404, 502, "The LLM endpoint refused the request with status 404: no"),
        (500, 502, "The LLM endpoint refused the request with status 500: no"),
        (502, 503, "The LLM endpoint failed with status 502: no"),
        (503, 503, "The LLM endpoint failed with status 503: no"),
        (504, 503, "The LLM endpoint failed with status 504: no"),
        (529, 503, "The LLM endpoint failed with status 529: no"),
    ],
)
@pytest.mark.parametrize("streamed", [False, True])
async def test_a_failed_answer_becomes_the_contracts_error(
    status: int, answered: int, detail: str, streamed: bool
) -> None:
    body = {"error": {"code": status, "message": " no ", "type": "some_error"}}
    client = upstream(lambda _request: httpx2.Response(status, json=body))

    with pytest.raises(ServiceError) as raised:
        await (parts(client) if streamed else client.complete(QUESTION, {}))

    assert (raised.value.status_code, str(raised.value)) == (answered, detail)


@pytest.mark.parametrize(
    ("error", "answered"),
    [
        (httpx2.ReadTimeout("slow"), 504),
        (httpx2.ConnectTimeout("slow"), 504),
        (httpx2.PoolTimeout("full"), 504),
        (httpx2.ConnectError("refused"), 503),
        (httpx2.ReadError("reset"), 503),
        (httpx2.RemoteProtocolError("cut"), 503),
    ],
)
@pytest.mark.parametrize("streamed", [False, True])
async def test_no_answer_is_a_timeout_or_an_upstream_that_cant_be_reached(
    error: httpx2.HTTPError, answered: int, streamed: bool
) -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise error

    client = upstream(handler)

    with pytest.raises(ServiceError) as raised:
        await (parts(client) if streamed else client.complete(QUESTION, {}))

    assert raised.value.status_code == answered


async def until_failure(
    client: OpenAICompatibleClient,
) -> tuple[list[StreamPart], ServiceError]:
    """A stream's parts, and the failure that ended it."""
    got: list[StreamPart] = []
    try:
        async for part in client.stream(QUESTION, {}):
            got.append(part)
    except ServiceError as failure:
        return got, failure
    raise AssertionError("the stream didn't fail")


class Breaking(httpx2.AsyncByteStream):
    """A stream's body that sends its start, then fails."""

    def __init__(self, start: str, error: httpx2.HTTPError) -> None:
        self._start, self._error = start.encode(), error

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._start
        raise self._error


@pytest.mark.parametrize(
    ("error", "answered"), [(httpx2.ReadTimeout("silent"), 504), (httpx2.ReadError("reset"), 503)]
)
async def test_a_stream_that_stops_fails_after_its_pieces(
    error: httpx2.HTTPError, answered: int
) -> None:
    client = upstream(
        lambda _request: httpx2.Response(200, stream=Breaking(chunk({"content": "A"}), error))
    )

    got, failure = await until_failure(client)

    assert got == [ContentDelta(text="A")]
    assert failure.status_code == answered


@pytest.mark.parametrize(
    ("error", "answered"),
    [
        ({"code": 429, "message": "slow down", "type": "rate_limit_error"}, 429),
        ({"code": 503, "message": "loading", "type": "unavailable_error"}, 503),
        ({"code": 400, "message": "no", "type": "invalid_request_error"}, 502),
        ({"code": "503", "message": "a code that isn't a number"}, 502),
        ({"code": True, "message": "nor is this"}, 502),
        ({"message": "no code"}, 502),
        ("just a text", 502),
    ],
)
async def test_an_error_inside_a_stream_is_mapped_by_its_code(error: Any, answered: int) -> None:
    body = chunk({"content": "A"}) + f"data: {json.dumps({'error': error})}\n\n"

    got, failure = await until_failure(upstream(streams(body)))

    assert got == [ContentDelta(text="A")]
    assert failure.status_code == answered


@pytest.mark.parametrize(
    "body", ["not JSON", "[]", '{"choices": []}', '{"choices": [{"message": "text"}]}']
)
async def test_a_whole_answer_that_cant_be_read_is_a_refusal(body: str) -> None:
    client = upstream(lambda _request: httpx2.Response(200, content=body.encode()))

    with pytest.raises(ServiceError) as raised:
        await client.complete(QUESTION, {})

    assert raised.value.status_code == 502


@pytest.mark.parametrize("data", ["not JSON", "[]", '"text"'])
async def test_a_chunk_that_cant_be_read_is_a_refusal(data: str) -> None:
    with pytest.raises(ServiceError) as raised:
        await parts(upstream(streams(f"data: {data}\n\n")))

    assert raised.value.status_code == 502


@pytest.mark.parametrize(
    ("status", "ready"), [(200, True), (400, True), (429, False), (503, False)]
)
async def test_readiness_is_a_completion_of_one_token(status: int, ready: bool) -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(status, json={})

    client = upstream(handler, llm_timeout_seconds=2)

    assert await client.is_ready() is ready
    body = json.loads(sent[0].content)
    assert (body["max_tokens"], body["model"]) == (1, "local")
    # The setting's timeout, since it's shorter than a readiness check's own 5 s.
    assert sent[0].extensions["timeout"]["read"] == 2


async def test_an_upstream_that_cant_be_reached_isnt_ready() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    assert await upstream(handler).is_ready() is False


async def test_the_settings_shape_the_client() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=whole(role="assistant", content="A"))

    client = upstream(handler, llm_timeout_seconds=7)
    await client.complete(QUESTION, {})

    # Each wait has the setting's timeout: none is for the whole answer.
    assert sent[0].extensions["timeout"] == {"connect": 7, "read": 7, "write": 7, "pool": 7}
    await client.aclose()
    with pytest.raises(RuntimeError):
        await client.complete(QUESTION, {})


async def test_the_factory_makes_the_client_the_provider_names() -> None:
    client = create_llm_client(Settings(llm_provider="openai-compatible", llm_max_connections=3))

    assert isinstance(client, OpenAICompatibleClient)
    await client.aclose()


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"error": {"message": "the reason"}}, ": the reason"),
        ({"error": "the reason"}, ": the reason"),
        ({"detail": "the reason"}, ": the reason"),
        ({"error": {"message": "x" * 300}}, ": " + "x" * 200),
        ({"error": {"message": "  "}}, "."),
        ({"error": {"code": 500}}, "."),
        (["a list"], "."),
        (None, "."),
    ],
)
def test_an_errors_reason_is_the_upstreams_own(body: object, expected: str) -> None:
    assert reason(body) == expected
