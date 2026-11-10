"""The fake upstream server: the contract's answer and pace, in llama.cpp's chunks, and each
`fake_error` shown as llama.cpp shows a failure (spec/decisions/0023).

It's checked alone here, as a backend's client would call it. The backends reach it from plan
step 2.2.
"""

import time
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest

from bench.compose import Compose
from bench.fake import answer
from bench.pace import Pace, Tolerance, lateness_ms
from conformance.conftest import DEFAULTS, PACED
from conformance.helpers import HI, Check
from conformance.upstream import DONE, PATH, Upstream, completions

# How each status of `fake_error` shows: the HTTP status, which is the error's code, and its type.
SHOWN = {
    429: (429, "rate_limit_error"),
    502: (400, "invalid_request_error"),
    503: (503, "unavailable_error"),
}
USAGE = {"stream_options": {"include_usage": True}}


@pytest.fixture(scope="module")
def upstream(compose: Compose) -> Iterator[Upstream]:
    upstream = Upstream(compose)
    yield upstream
    upstream.restore()


def counts(usage: dict[str, Any]) -> dict[str, int]:
    """The usage's three counts, without llama.cpp's own details."""
    return {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")}


@pytest.mark.parametrize("parameters", [{}, {"max_tokens": 5}, {"max_tokens": 0}])
def test_a_stream_is_the_contracts_answer(
    upstream: Upstream, check: Check, parameters: dict[str, Any]
) -> None:
    expected = answer(DEFAULTS, check.tokens, HI, parameters)

    streamed = completions(upstream.serve(DEFAULTS), {"messages": HI, **parameters, **USAGE})

    assert streamed.response.headers["content-type"] == "text/event-stream"
    assert [text for _, text, _ in streamed.deltas()] == list(expected.content)
    *_, finish, usage, done = (chunk.data for chunk in streamed.chunks)
    assert done == DONE
    assert finish["choices"][0]["finish_reason"] == expected.finish_reason
    assert finish["choices"][0]["delta"] == {}
    assert usage["choices"] == []
    assert counts(usage["usage"]) == expected.usage
    assert streamed.chunks[0].data["choices"][0]["delta"] == {"role": "assistant", "content": None}


def test_the_usage_comes_only_when_asked_for(upstream: Upstream) -> None:
    streamed = completions(upstream.serve(DEFAULTS), {"messages": HI, "max_tokens": 2})

    assert all("usage" not in chunk.data for chunk in streamed.chunks[:-1])
    assert streamed.chunks[-1].data == DONE


def test_a_whole_answer_is_the_contracts(upstream: Upstream, check: Check) -> None:
    expected = answer(PACED, check.tokens, HI, {"max_tokens": 5})

    response = upstream.serve(PACED).post(PATH, json={"messages": HI, "max_tokens": 5})

    assert response.status_code == 200
    body = response.json()
    message = body["choices"][0]["message"]
    assert message["content"] == "".join(expected.content)
    assert message["reasoning_content"] == "".join(expected.reasoning)
    assert body["choices"][0]["finish_reason"] == expected.finish_reason
    assert counts(body["usage"]) == expected.usage
    assert body["object"] == "chat.completion"


def test_the_stream_keeps_the_pace(
    upstream: Upstream, check: Check, tolerance: Tolerance, report: list[str]
) -> None:
    client = upstream.serve(PACED)
    expected = answer(PACED, check.tokens, HI, {})
    # One stream first, untimed, as for the backends.
    completions(client, {"messages": HI})

    streamed = completions(client, {"messages": HI})

    deltas = streamed.deltas()
    reasoning = [text for key, text, _ in deltas if key == "reasoning_content"]
    content = [text for key, text, _ in deltas if key == "content"]
    assert (reasoning, content) == (list(expected.reasoning), list(expected.content))
    # The reasoning's chunks all come before the answer's.
    assert [key for key, _, _ in deltas[: len(reasoning)]] == ["reasoning_content"] * len(reasoning)
    due = [PACED.due_ms(index) for index in range(len(deltas))]
    pace = Pace(tuple(lateness_ms(streamed.sent, [at for _, _, at in deltas], due)))
    headers_ms = (streamed.headers_at - streamed.sent) / 1e6
    report.append(
        f"fake-server: {len(deltas)} tokens, lateness median {pace.median_ms:.2f} ms, "
        f"min {min(pace.lateness_ms):.2f}, max {max(pace.lateness_ms):.2f}; "
        f"the last quarter {pace.drift_ms or 0:+.2f} ms on the first; "
        f"headers at {headers_ms:.1f} ms"
    )
    # As llama.cpp's, its headers leave with the first token, not before.
    assert headers_ms >= due[0], "the headers came before the first token's time"
    assert pace.problems(tolerance) == []


def test_the_whole_answer_comes_at_the_last_tokens_time(
    upstream: Upstream, check: Check, tolerance: Tolerance
) -> None:
    client = upstream.serve(PACED)
    body = {"messages": HI, "max_tokens": 3}
    due = answer(PACED, check.tokens, HI, {"max_tokens": 3}).due_ms
    late = []
    for _ in range(5):
        sent = time.perf_counter_ns()
        client.post(PATH, json=body).read()
        late.append((time.perf_counter_ns() - sent) / 1e6 - due)

    assert Pace(tuple(late)).problems(tolerance, drift=False) == []


@pytest.mark.parametrize("status", sorted(SHOWN))
@pytest.mark.parametrize("stream", [False, True])
def test_before_the_first_token_a_fake_error_is_a_plain_http_error(
    upstream: Upstream, status: int, stream: bool
) -> None:
    code, kind = SHOWN[status]
    body = {"messages": HI, "stream": stream, "fake_error": {"status": status}}

    response = upstream.serve(DEFAULTS).post(PATH, json=body)

    assert response.status_code == code
    assert response.headers["content-type"].startswith("application/json")
    error = response.json()["error"]
    assert (error["code"], error["type"]) == (code, kind)
    assert isinstance(error["message"], str)


@pytest.mark.parametrize("status", sorted(SHOWN))
def test_after_tokens_a_fake_error_is_an_error_chunk_that_ends_the_stream(
    upstream: Upstream, check: Check, status: int
) -> None:
    code, kind = SHOWN[status]
    fake_error = {"status": status, "after_tokens": 2}

    streamed = completions(upstream.serve(DEFAULTS), {"messages": HI, "fake_error": fake_error})

    assert streamed.response.status_code == 200
    assert [text for _, text, _ in streamed.deltas()] == list(check.tokens[:2])
    last = streamed.chunks[-1].data
    assert (last["error"]["code"], last["error"]["type"]) == (code, kind)
    assert all(chunk.data != DONE for chunk in streamed.chunks)


def until_silent(client: httpx2.Client, body: dict[str, Any]) -> bytes:
    """What the server sends before it says nothing for half a second."""
    read = b""
    try:
        with client.stream("POST", PATH, json=body, timeout=0.5) as response:
            for raw in response.iter_raw():
                read += raw
    except httpx2.ReadTimeout:
        return read
    raise AssertionError(f"it answered: {read!r}")


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("after_tokens", [0, 1])
def test_a_504_is_no_answer(upstream: Upstream, stream: bool, after_tokens: int) -> None:
    client = upstream.serve(DEFAULTS)
    fake_error = {"status": 504, "after_tokens": after_tokens}
    body = {"messages": HI, "stream": stream, "fake_error": fake_error}

    read = until_silent(client, body)

    # A stream sends the tokens made before it goes silent; nothing says it ended.
    assert read.count(b'"content":"') == (after_tokens if stream else 0)
    assert b"[DONE]" not in read
    assert b"error" not in read


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "fake_error", ["503", {}, {"status": 500}, {"status": 503, "after_tokens": -1}]
)
def test_a_malformed_fake_error_is_refused_at_once(
    upstream: Upstream, stream: bool, fake_error: Any
) -> None:
    body = {"messages": HI, "stream": stream, "fake_error": fake_error}
    client = upstream.serve(PACED)
    sent = time.perf_counter_ns()

    response = client.post(PATH, json=body)

    # Well before the first token's time, 100 ms.
    assert (time.perf_counter_ns() - sent) / 1e6 < PACED.first_token_ms / 2
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"


@pytest.mark.parametrize("body", ['{"messages":', '{"messages": "no"}', '{"stream": true}'])
def test_a_request_it_cant_read_is_refused_as_llama_cpp_does(upstream: Upstream, body: str) -> None:
    response = upstream.serve(DEFAULTS).post(PATH, content=body)

    assert response.status_code == 400
    error = response.json()["error"]
    assert (error["code"], error["type"]) == (400, "invalid_request_error")


def test_health_answers_as_llama_cpps(upstream: Upstream) -> None:
    response = upstream.serve(DEFAULTS).get("/health")

    assert (response.status_code, response.json()) == (200, {"status": "ok"})


def test_a_client_that_leaves_is_logged(upstream: Upstream) -> None:
    client = upstream.serve(PACED)

    # The role and two tokens, then the client closes its connection.
    streamed = completions(client, {"messages": HI}, chunks=3)

    identifier = streamed.chunks[0].data["id"]
    deadline = time.monotonic() + 5
    while identifier not in (logs := upstream.logs()) and time.monotonic() < deadline:
        time.sleep(0.05)
    lines = [line for line in logs.splitlines() if identifier in line]
    assert len(lines) == 1, logs
    assert '"msg":"closed early"' in lines[0]
    assert '"stream":true' in lines[0]
