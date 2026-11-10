"""A backend refuses to start with an invalid setting (contract/README.md#settings)."""

import pytest

from bench.compose import Compose
from bench.fake import FakeSettings
from conformance.helpers import Backend

INVALID = {
    "a count below its minimum": {"FAKE_ANSWER_TOKENS": "0"},
    "a time that isn't a number": {"FAKE_TOKEN_GAP_MS": "soon"},
    "an unknown upstream": {"LLM_PROVIDER": "psychic"},
    "an upstream's address without a scheme": {"LLM_BASE_URL": "fake-server:8080"},
    "no time to wait for the upstream": {"LLM_TIMEOUT_SECONDS": "0"},
    "no connection to the upstream": {"LLM_MAX_CONNECTIONS": "0"},
}


@pytest.mark.parametrize("setting", INVALID.values(), ids=INVALID.keys())
def test_an_invalid_setting_stops_the_start_up(
    backend: Backend, compose: Compose, setting: dict[str, str]
) -> None:
    backend.forget()

    started = compose.up(backend.service, backend.environment(FakeSettings()) | setting)

    state = compose.state(backend.service)
    assert not started, f"it started with {setting}"
    assert (state.state, state.exit_code != 0) == ("exited", True), compose.logs(backend.service)
