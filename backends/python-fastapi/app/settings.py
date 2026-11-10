"""The settings, read from the environment at start-up (contract/README.md#settings)."""

from typing import Literal

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every setting the contract names, each with its default. An invalid value stops the
    start-up."""

    model_config = SettingsConfigDict(frozen=True)

    # `fake` answers from the in-process fake; `openai-compatible` calls the upstream.
    llm_provider: Literal["fake", "openai-compatible"] = "fake"

    # The upstream (contract/README.md#the-upstream).
    llm_base_url: HttpUrl = HttpUrl("http://fake-server:8080/v1")
    llm_model: str = Field(default="local", min_length=1)
    llm_api_key: SecretStr = Field(default=SecretStr("local"), min_length=1)
    llm_timeout_seconds: float = Field(default=300, gt=0, allow_inf_nan=False)
    llm_max_connections: int = Field(default=1000, ge=1)

    # The in-process fake (contract/README.md#the-fakes).
    fake_answer_tokens: int = Field(default=256, ge=1)
    fake_reasoning_tokens: int = Field(default=0, ge=0)
    fake_first_token_ms: int = Field(default=0, ge=0)
    fake_token_gap_ms: int = Field(default=0, ge=0)
