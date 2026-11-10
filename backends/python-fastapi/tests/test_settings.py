"""The settings, from the environment (contract/README.md#settings)."""

import pytest
from pydantic import ValidationError

from app.settings import Settings


def test_the_defaults() -> None:
    settings = Settings()

    assert settings.llm_provider == "fake"
    assert (settings.fake_answer_tokens, settings.fake_reasoning_tokens) == (256, 0)
    assert (settings.fake_first_token_ms, settings.fake_token_gap_ms) == (0, 0)


def test_the_upstreams_defaults() -> None:
    settings = Settings()

    assert str(settings.llm_base_url) == "http://fake-server:8080/v1"
    assert (settings.llm_model, settings.llm_api_key.get_secret_value()) == ("local", "local")
    assert (settings.llm_timeout_seconds, settings.llm_max_connections) == (300, 1000)


def test_the_environment_sets_them(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_TOKEN_GAP_MS", "20")
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "1.5")

    settings = Settings()

    assert settings.fake_token_gap_ms == 20
    assert (settings.llm_provider, settings.llm_timeout_seconds) == ("openai-compatible", 1.5)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LLM_PROVIDER", "psychic"),
        ("LLM_BASE_URL", "fake-server:8080"),
        ("LLM_BASE_URL", ""),
        ("LLM_MODEL", ""),
        ("LLM_API_KEY", ""),
        ("LLM_TIMEOUT_SECONDS", "0"),
        ("LLM_TIMEOUT_SECONDS", "inf"),
        ("LLM_TIMEOUT_SECONDS", "soon"),
        ("LLM_MAX_CONNECTIONS", "0"),
        ("LLM_MAX_CONNECTIONS", "1.5"),
        ("FAKE_ANSWER_TOKENS", "0"),
        ("FAKE_REASONING_TOKENS", "-1"),
        ("FAKE_FIRST_TOKEN_MS", "1.5"),
        ("FAKE_TOKEN_GAP_MS", "soon"),
    ],
)
def test_an_invalid_value_is_refused(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings()
