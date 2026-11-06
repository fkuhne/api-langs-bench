"""The LLM client the settings ask for."""

from app.fake.client import FakeLLMClient
from app.fake.tokens import load_tokens
from app.llm.port import LLMClient
from app.settings import Settings


def create_llm_client(settings: Settings) -> LLMClient:
    """The in-process fake, the only provider until the upstream's client (plan step 2.2)."""
    return FakeLLMClient(settings, load_tokens())
