"""Liveness and readiness (contract/README.md#the-endpoints)."""

import httpx2
import pytest

from app.fake.client import FakeLLMClient
from tests.conftest import UseLLM

pytestmark = pytest.mark.anyio


class NotReady(FakeLLMClient):
    async def is_ready(self) -> bool:
        return False


async def test_liveness(client: httpx2.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert (response.status_code, response.json()) == (200, {"status": "ok"})


async def test_readiness_with_the_fake(client: httpx2.AsyncClient) -> None:
    response = await client.get("/api/health/ready")

    assert response.status_code == httpx2.codes.OK
    assert response.json() == {"status": "ok", "checks": {"llm": "ok"}}


async def test_readiness_answers_503_while_the_upstream_is_unavailable(
    client: httpx2.AsyncClient, use_llm: UseLLM, fake: FakeLLMClient
) -> None:
    use_llm(NotReady(fake._settings, fake._tokens))

    response = await client.get("/api/health/ready")

    assert response.status_code == httpx2.codes.SERVICE_UNAVAILABLE
    assert response.json() == {"status": "unavailable", "checks": {"llm": "unavailable"}}
