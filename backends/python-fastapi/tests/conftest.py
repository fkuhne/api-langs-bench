"""Shared fixtures. Route tests use an async client over ASGI, with the fake on a fake clock."""

import os
from collections.abc import AsyncIterator, Callable

import httpx2
import pytest
from fastapi import FastAPI

from app.fake.client import FakeLLMClient
from app.fake.tokens import load_tokens
from app.llm.dependencies import get_llm_client
from app.llm.port import LLMClient
from app.main import create_app
from app.settings import Settings
from tests.helpers import FakeClock

UseLLM = Callable[[LLMClient], None]


@pytest.fixture(autouse=True)
def hermetic_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts from the defaults, whatever the shell exports."""
    for name in list(os.environ):
        if name.startswith(("LLM_", "FAKE_")):
            monkeypatch.delenv(name)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake(clock: FakeClock) -> FakeLLMClient:
    """The fake with the default settings, on the fake clock."""
    return FakeLLMClient(Settings(), load_tokens(), clock)


@pytest.fixture
def app(fake: FakeLLMClient) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_llm_client] = lambda: fake
    return app


@pytest.fixture
def use_llm(app: FastAPI) -> UseLLM:
    """Make the app's routes use another LLM client."""

    def use(llm: LLMClient) -> None:
        app.dependency_overrides[get_llm_client] = lambda: llm

    return use


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
