"""Each backend through llama.cpp's server, with a real model (spec/decisions/0025).

A real model's answers aren't fixed, so these check their shape, not their text. They run only
when asked, once the model is downloaded:

    docker compose up -d --wait llama-cpp
    docker compose run --rm conformance -m llama_cpp
"""

from collections.abc import Iterator
from typing import Any

import httpx2
import pytest

from bench.backends import BACKENDS, LLAMA_CPP, upstream_settings, url
from bench.compose import Compose
from conformance.helpers import Check, post, stream

pytestmark = pytest.mark.llama_cpp

QUESTION = [{"role": "user", "content": "In one sentence, what is an LLM?"}]
# Few tokens, so each answer is quick, and cut short.
TOKENS = 8


@pytest.fixture(scope="module", params=BACKENDS)
def through_llama(request: pytest.FixtureRequest, compose: Compose) -> Iterator[httpx2.Client]:
    """The backend, calling llama.cpp. llama.cpp is started first: at once, once its model is
    in its volume."""
    service = request.param
    compose.start(LLAMA_CPP, {})
    compose.start(service, upstream_settings(LLAMA_CPP))
    with httpx2.Client(base_url=url(service), timeout=120) as client:
        yield client
    # Left running with the settings `.env` gives, as Compose started it.
    compose.start(service, {})


def body(**parameters: Any) -> dict[str, Any]:
    return {"messages": QUESTION, "parameters": {"max_tokens": TOKENS, **parameters}}


def test_it_is_ready(through_llama: httpx2.Client, check: Check) -> None:
    response = through_llama.get("/api/health/ready")

    assert check.json(response, 200, "Readiness") == {"status": "ok", "checks": {"llm": "ok"}}


def test_the_whole_answer_reasons_and_is_cut_short(
    through_llama: httpx2.Client, check: Check
) -> None:
    got = check.json(post(through_llama, "/api/chat", body()), 200, "Completion")

    # The model reasons first, by default, so 8 tokens are all reasoning.
    assert got["reasoning"]
    assert got["model"].endswith(".gguf")
    assert got["finish_reason"] == "length"
    assert got["usage"]["completion_tokens"] == TOKENS


def test_the_stream_is_one_event_for_each_piece(through_llama: httpx2.Client, check: Check) -> None:
    events = check.events(stream(through_llama, body()))

    *pieces, (last, end) = events
    assert last == "done"
    assert end["finish_reason"] == "length"
    assert {name for name, _ in pieces} == {"reasoning"}
    # One event for each token the model made, never more.
    assert 1 <= len(pieces) <= end["usage"]["completion_tokens"] == TOKENS


def test_a_parameter_reaches_the_model(through_llama: httpx2.Client, check: Check) -> None:
    # Qwen's own switch, passed on unchanged: no reasoning, so the tokens are the answer.
    no_thinking = body(chat_template_kwargs={"enable_thinking": False})

    events = check.events(stream(through_llama, no_thinking))

    names = {name for name, _ in events[:-1]}
    assert names == {"token"}, events


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/stream"])
def test_a_refused_parameter_is_a_502(
    through_llama: httpx2.Client, check: Check, path: str
) -> None:
    refused = body(temperature="hot")

    if path == "/api/chat":
        check.json(post(through_llama, path, refused), 502, "Error")
    else:
        assert check.events(stream(through_llama, refused)) == [("error", {"status": 502})]


def test_it_is_unready_while_llama_cpp_is_stopped(
    through_llama: httpx2.Client, check: Check, compose: Compose
) -> None:
    compose.stop(LLAMA_CPP)
    try:
        ready = through_llama.get("/api/health/ready")
        whole = post(through_llama, "/api/chat", body())
    finally:
        compose.start(LLAMA_CPP, {})

    assert check.json(ready, 503, "Readiness")["checks"] == {"llm": "unavailable"}
    check.json(whole, 503, "Error")
    assert through_llama.get("/api/health/ready").status_code == 200
