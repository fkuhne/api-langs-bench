"""The LLM client the settings ask for."""

from app.fake.client import FakeLLMClient
from app.fake.tokens import load_tokens
from app.llm.port import LLMClient
from app.settings import Settings
from app.upstream.client import OpenAICompatibleClient


def create_llm_client(settings: Settings) -> LLMClient:
    """The in-process fake, or the upstream client, as `LLM_PROVIDER` says."""
    if settings.llm_provider == "fake":
        return FakeLLMClient(settings, load_tokens())
    return OpenAICompatibleClient(settings)
