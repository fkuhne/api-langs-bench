"""The contract's schemas say what its page says (contract/README.md)."""

from typing import Any

import pytest

from bench.contract import Contract

CHAT_REQUEST = "#/components/schemas/ChatRequest"
# One event of the stream, as `POST /api/chat/stream` describes it.
STREAM_EVENT = (
    "#/paths/~1api~1chat~1stream/post/responses/200/content/text~1event-stream/itemSchema"
)
HI = [{"role": "user", "content": "Hi"}]


@pytest.fixture(scope="module")
def contract() -> Contract:
    return Contract()


def test_the_documents_own_example_is_a_valid_request(contract: Contract) -> None:
    body = contract.document["components"]["requestBodies"]["Chat"]["content"]["application/json"]
    example = body["examples"]["short"]["value"]

    assert contract.validator(CHAT_REQUEST).is_valid(example)


@pytest.mark.parametrize(
    "request_body",
    [
        pytest.param({"messages": HI}, id="no parameters"),
        pytest.param({"messages": HI, "other": 1}, id="another field, ignored"),
        pytest.param(
            {"messages": HI, "parameters": {"fake_error": {"status": 503, "after_tokens": 2}}},
            id="fake_error",
        ),
    ],
)
def test_a_valid_request(contract: Contract, request_body: dict[str, Any]) -> None:
    assert contract.validator(CHAT_REQUEST).is_valid(request_body)


@pytest.mark.parametrize(
    "request_body",
    [
        pytest.param({}, id="no messages"),
        pytest.param({"messages": []}, id="empty messages"),
        pytest.param({"messages": [{"role": "tool", "content": "x"}]}, id="an unknown role"),
        pytest.param({"messages": [{"role": "user", "content": ""}]}, id="empty content"),
        pytest.param(
            {"messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}]},
            id="content parts",
        ),
        pytest.param({"messages": HI, "parameters": {"stream": True}}, id="a reserved key"),
        pytest.param({"messages": HI, "parameters": [1]}, id="parameters not an object"),
    ],
)
def test_an_invalid_request(contract: Contract, request_body: dict[str, Any]) -> None:
    assert not contract.validator(CHAT_REQUEST).is_valid(request_body)


@pytest.mark.parametrize("name", ["reasoning", "token", "done", "error"])
def test_each_event_of_the_page_is_in_the_stream(contract: Contract, name: str) -> None:
    assert contract.validator(STREAM_EVENT).is_valid({"event": name, "data": "{}"})


@pytest.mark.parametrize(
    "event",
    [
        pytest.param({"event": "ping", "data": "{}"}, id="an unknown event"),
        pytest.param({"data": "{}"}, id="no event name"),
    ],
)
def test_any_other_event_is_refused(contract: Contract, event: dict[str, str]) -> None:
    assert not contract.validator(STREAM_EVENT).is_valid(event)


def test_the_page_counts_the_tokens_right(contract: Contract) -> None:
    assert len(contract.tokens) == 175
    assert all(token for token in contract.tokens)
