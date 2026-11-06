"""The chat endpoints answer as the contract says (contract/README.md)."""

from typing import Any

import httpx2
import pytest

from tests.helpers import events

pytestmark = pytest.mark.anyio

QUESTION: dict[str, Any] = {
    "messages": [{"role": "user", "content": "In one sentence, what is an LLM?"}],
    "parameters": {"max_tokens": 5},
}
USAGE = {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}


def asking(**parameters: Any) -> dict[str, Any]:
    return {"messages": QUESTION["messages"], "parameters": parameters}


async def test_chat_returns_the_whole_answer(client: httpx2.AsyncClient) -> None:
    response = await client.post("/api/chat", json=QUESTION)

    assert response.status_code == httpx2.codes.OK
    assert response.json() == {
        "content": "A backend in front of",
        "reasoning": None,
        "model": "fake",
        "finish_reason": "length",
        "usage": USAGE,
    }


async def test_the_stream_sends_each_token_then_done(client: httpx2.AsyncClient) -> None:
    response = await client.post("/api/chat/stream", json=QUESTION)

    assert response.status_code == httpx2.codes.OK
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert events(response.text) == [
        ("token", {"text": "A"}),
        ("token", {"text": " backend"}),
        ("token", {"text": " in"}),
        ("token", {"text": " front"}),
        ("token", {"text": " of"}),
        ("done", {"model": "fake", "finish_reason": "length", "usage": USAGE}),
    ]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="no messages"),
        pytest.param({"messages": []}, id="empty messages"),
        pytest.param({"messages": [{"role": "tool", "content": "x"}]}, id="an unknown role"),
        pytest.param({"messages": [{"role": "user", "content": ""}]}, id="empty content"),
        pytest.param({"messages": [{"role": "user", "content": 1}]}, id="a number as content"),
        pytest.param(
            {"messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}]},
            id="content parts",
        ),
        pytest.param(asking(stream=True), id="a reserved key"),
        pytest.param({"messages": QUESTION["messages"], "parameters": [1]}, id="a list"),
    ],
)
@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/stream"])
async def test_an_invalid_body_answers_422(
    client: httpx2.AsyncClient, path: str, body: dict[str, Any]
) -> None:
    response = await client.post(path, json=body)

    assert response.status_code == httpx2.codes.UNPROCESSABLE_CONTENT
    assert "detail" in response.json()


async def test_other_fields_are_ignored(client: httpx2.AsyncClient) -> None:
    response = await client.post("/api/chat", json={**QUESTION, "other": 1})

    assert response.status_code == httpx2.codes.OK


@pytest.mark.parametrize("status", [429, 502, 503, 504])
async def test_an_upstream_failure_answers_its_status(
    client: httpx2.AsyncClient, status: int
) -> None:
    response = await client.post("/api/chat", json=asking(fake_error={"status": status}))

    assert response.status_code == status
    assert isinstance(response.json()["detail"], str)


async def test_a_failure_ends_the_stream_with_an_error_event(client: httpx2.AsyncClient) -> None:
    body = asking(fake_error={"status": 504, "after_tokens": 2})

    response = await client.post("/api/chat/stream", json=body)

    assert response.status_code == httpx2.codes.OK
    sent = events(response.text)
    assert [name for name, _ in sent] == ["token", "token", "error"]
    assert sent[-1][1]["status"] == 504


async def test_a_malformed_fake_error_is_refused_with_502(client: httpx2.AsyncClient) -> None:
    whole = await client.post("/api/chat", json=asking(fake_error="soon"))
    streamed = await client.post("/api/chat/stream", json=asking(fake_error="soon"))

    assert whole.status_code == httpx2.codes.BAD_GATEWAY
    assert events(streamed.text) == [("error", {"status": 502, "detail": whole.json()["detail"]})]


async def test_parameters_reach_the_model_as_given(client: httpx2.AsyncClient) -> None:
    body = asking(max_tokens=1, temperature=0.7, nested={"a": [1, None]})

    response = await client.post("/api/chat", json=body)

    assert response.json()["content"] == "A"
