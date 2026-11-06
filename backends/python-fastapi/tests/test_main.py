"""The app as uvicorn runs it: its start-up, and a client that leaves mid-stream."""

import asyncio
from collections.abc import AsyncGenerator, Sequence

import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.fake.client import FakeLLMClient
from app.fake.tokens import load_tokens
from app.llm.dependencies import get_llm_client
from app.llm.port import ChatMessage, Parameters, StreamPart
from app.main import create_app
from app.settings import Settings


def test_the_start_up_makes_the_fake_from_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_ANSWER_TOKENS", "2")
    body = {"messages": [{"role": "user", "content": "Hi"}]}

    with TestClient(create_app()) as client:
        ready = client.get("/api/health/ready")
        answer = client.post("/api/chat", json=body)

    assert ready.status_code == httpx2.codes.OK
    assert answer.json()["content"] == "A backend"


def test_an_invalid_setting_stops_the_start_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_ANSWER_TOKENS", "0")

    with pytest.raises(ValueError, match="fake_answer_tokens"), TestClient(create_app()):
        pass


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_the_served_docs_are_off(path: str) -> None:
    with TestClient(create_app()) as client:
        assert client.get(path).status_code == httpx2.codes.NOT_FOUND


class WatchedFake(FakeLLMClient):
    """The fake, noting each token it makes, and when its stream is closed."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, load_tokens())
        self.made = 0
        self.closed = asyncio.Event()

    async def stream(
        self, messages: Sequence[ChatMessage], parameters: Parameters
    ) -> AsyncGenerator[StreamPart]:
        try:
            async for part in super().stream(messages, parameters):
                self.made += 1
                yield part
        finally:
            self.closed.set()


@pytest.mark.anyio
async def test_a_client_that_leaves_stops_the_fake() -> None:
    """Over a real socket, as uvicorn serves it: the stream stops soon after the client leaves."""
    fake = WatchedFake(Settings(fake_token_gap_ms=20, fake_answer_tokens=1000))
    app = create_app()
    app.dependency_overrides[get_llm_client] = lambda: fake
    server = uvicorn.Server(uvicorn.Config(app, port=0, log_level="warning", lifespan="off"))
    serving = asyncio.create_task(server.serve())
    # uvicorn has no event for its start, only this flag.
    while not server.started:  # noqa: ASYNC110
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    body = {"messages": [{"role": "user", "content": "Hi"}]}

    async with (
        httpx2.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client,
        client.stream("POST", "/api/chat/stream", json=body) as response,
    ):
        lines = response.aiter_lines()
        while (await anext(lines)) != 'data: {"text":" backend"}':
            pass
    left_at = fake.made
    await asyncio.wait_for(fake.closed.wait(), timeout=1)

    server.should_exit = True
    await serving
    # FastAPI holds up to two events between the fake and the socket (decisions/0014).
    assert fake.made - left_at <= 3
