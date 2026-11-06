"""The settings, read from the environment at start-up (contract/README.md#settings)."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every setting the contract names, each with its default. An invalid value stops the
    start-up."""

    model_config = SettingsConfigDict(frozen=True)

    # `openai-compatible` arrives with the upstream's client, in plan step 2.2.
    llm_provider: Literal["fake"] = "fake"
    fake_answer_tokens: int = Field(default=256, ge=1)
    fake_reasoning_tokens: int = Field(default=0, ge=0)
    fake_first_token_ms: int = Field(default=0, ge=0)
    fake_token_gap_ms: int = Field(default=0, ge=0)
