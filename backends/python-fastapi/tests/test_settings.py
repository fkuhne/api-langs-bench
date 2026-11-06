"""The settings, from the environment (contract/README.md#settings)."""

import pytest
from pydantic import ValidationError

from app.settings import Settings


def test_the_defaults() -> None:
    settings = Settings()

    assert settings.llm_provider == "fake"
    assert (settings.fake_answer_tokens, settings.fake_reasoning_tokens) == (256, 0)
    assert (settings.fake_first_token_ms, settings.fake_token_gap_ms) == (0, 0)


def test_the_environment_sets_them(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_TOKEN_GAP_MS", "20")

    assert Settings().fake_token_gap_ms == 20


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LLM_PROVIDER", "openai-compatible"),
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
