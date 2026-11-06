"""The LLM port: what the backend needs from a chat model. ai-bootstrap's `app/llm/llm_client.py`,
cut to text (contract/README.md#the-request)."""

from collections.abc import AsyncGenerator, Mapping, Sequence
from typing import Annotated, Literal, Protocol

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue

Role = Literal["system", "user", "assistant"]

# Generation parameters, such as max_tokens, temperature or seed, sent on as given.
Parameters = Mapping[str, JsonValue]

# Parameters the backend sets itself, which a request can't send.
RESERVED_PARAMETERS = frozenset({"model", "messages", "stream", "stream_options"})


def _not_reserved(parameters: dict[str, JsonValue]) -> dict[str, JsonValue]:
    if reserved := sorted(RESERVED_PARAMETERS & parameters.keys()):
        raise ValueError(f"the backend sets these itself: {', '.join(reserved)}")
    return parameters


# Generation parameters as a request carries them.
RequestParameters = Annotated[dict[str, JsonValue], AfterValidator(_not_reserved)]


class ChatMessage(BaseModel):
    """One message of the conversation sent to the model."""

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str = Field(min_length=1)


class Usage(BaseModel):
    """Tokens one answer used, as the upstream counts them."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class Completion(BaseModel):
    """A whole answer, with the model's reasoning when it shows it."""

    model_config = ConfigDict(frozen=True)

    content: str
    reasoning: str | None = None
    model: str
    finish_reason: str | None = None
    usage: Usage | None = None


class ContentDelta(BaseModel):
    """The next piece of the answer."""

    model_config = ConfigDict(frozen=True)

    text: str


class ReasoningDelta(BaseModel):
    """The next piece of the model's reasoning, which comes before the answer."""

    model_config = ConfigDict(frozen=True)

    text: str


class StreamEnd(BaseModel):
    """The last part of a stream that ended normally."""

    model_config = ConfigDict(frozen=True)

    model: str
    finish_reason: str | None = None
    usage: Usage | None = None


StreamPart = ContentDelta | ReasoningDelta | StreamEnd


class LLMClient(Protocol):
    """A chat model the backend can call. Every method raises `app.errors.ServiceError`s on
    failure."""

    async def complete(self, messages: Sequence[ChatMessage], parameters: Parameters) -> Completion:
        """Return the whole answer to `messages`."""
        ...

    def stream(
        self, messages: Sequence[ChatMessage], parameters: Parameters
    ) -> AsyncGenerator[StreamPart]:
        """Yield the reasoning and the answer piece by piece, then a `StreamEnd`. Closing the
        generator early stops the model."""
        ...

    async def is_ready(self) -> bool:
        """Tell whether the model can take requests right now."""
        ...

    async def aclose(self) -> None:
        """Release connections and other resources."""
        ...
