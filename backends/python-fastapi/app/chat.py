"""The chat endpoints: the messages go to the model, its answer comes back whole or streamed
(contract/README.md). ai-bootstrap's `app/modules/chat/router.py`, cut to text."""

from collections.abc import AsyncIterable

from fastapi import APIRouter
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from app.errors import AppError, error_event
from app.llm.dependencies import LLMClientDep
from app.llm.port import (
    ChatMessage,
    Completion,
    ContentDelta,
    ReasoningDelta,
    RequestParameters,
    StreamEnd,
)

router = APIRouter(prefix="/chat", tags=["chat"])

# The event each stream part is sent as.
EVENTS: dict[type, str] = {ReasoningDelta: "reasoning", ContentDelta: "token", StreamEnd: "done"}


class ChatRequest(BaseModel):
    """The conversation so far, and any generation parameters. Other fields are ignored."""

    messages: list[ChatMessage] = Field(min_length=1)
    parameters: RequestParameters = Field(default_factory=dict)


@router.post("", summary="Ask the model, and get its whole answer")
async def chat(body: ChatRequest, llm: LLMClientDep) -> Completion:
    return await llm.complete(body.messages, body.parameters)


@router.post(
    "/stream",
    response_class=EventSourceResponse,
    summary="Ask the model, and stream its answer as server-sent events",
)
async def chat_stream(body: ChatRequest, llm: LLMClientDep) -> AsyncIterable[ServerSentEvent]:
    try:
        async for part in llm.stream(body.messages, body.parameters):
            yield ServerSentEvent(event=EVENTS[type(part)], data=part)
    except AppError as error:
        yield error_event(error)
