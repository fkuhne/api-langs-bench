"""The upstream client: an OpenAI-compatible chat API, such as llama.cpp's server or the fake
server, called with httpx2 alone (contract/README.md#the-upstream, spec/decisions/0024).

It's ai-bootstrap's `OpenAICompatibleClient` without the OpenAI SDK, and without retries."""

import json
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import httpx2

from app.llm.port import (
    ChatMessage,
    Completion,
    ContentDelta,
    Parameters,
    ReasoningDelta,
    StreamEnd,
    StreamPart,
    Usage,
)
from app.settings import Settings
from app.upstream.errors import status_error, stream_error, transport_error, unreadable

# A readiness check waits this long at most, or the setting's timeout if that's shorter.
READINESS_TIMEOUT_SECONDS = 5.0

# Where servers put the model's reasoning: llama.cpp and DeepSeek use the first, Ollama and
# OpenRouter the second.
REASONING_FIELDS = ("reasoning_content", "reasoning")

# How a stream says it has ended.
DONE = "[DONE]"

BAD_REQUEST = 400


class OpenAICompatibleClient:
    """Calls `POST {LLM_BASE_URL}/chat/completions`, whole or streamed. It sends the caller's
    parameters as given, and adds none of its own."""

    def __init__(
        self, settings: Settings, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        """Tests pass a `transport`, so no request leaves the process."""
        self._model = settings.llm_model
        self._url = str(settings.llm_base_url).rstrip("/") + "/chat/completions"
        self._readiness_timeout = min(READINESS_TIMEOUT_SECONDS, settings.llm_timeout_seconds)
        self._client = httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}"},
            # For each wait in which nothing arrives: a connection, the answer's start, and
            # each piece of its body. Not for the whole answer.
            timeout=httpx2.Timeout(settings.llm_timeout_seconds),
            # As many connections kept idle as may be open, so a steady load reuses them.
            limits=httpx2.Limits(
                max_connections=settings.llm_max_connections,
                max_keepalive_connections=settings.llm_max_connections,
            ),
            transport=transport,
        )

    async def complete(self, messages: Sequence[ChatMessage], parameters: Parameters) -> Completion:
        try:
            response = await self._client.post(self._url, json=self._body(messages, parameters))
        except httpx2.HTTPError as error:
            raise transport_error(error) from error
        body = _json(response.content)
        if not response.is_success:
            raise status_error(response.status_code, body)
        choice = _first_choice(body)
        message = choice.get("message") if choice is not None else None
        if not isinstance(body, dict) or not isinstance(message, dict):
            raise unreadable()
        content = message.get("content")
        return Completion(
            content=content if isinstance(content, str) else "",
            reasoning=_reasoning(message) or None,
            model=_text(body.get("model")) or self._model,
            finish_reason=_text(choice.get("finish_reason")) if choice else None,
            usage=_usage(body.get("usage")),
        )

    async def stream(
        self, messages: Sequence[ChatMessage], parameters: Parameters
    ) -> AsyncGenerator[StreamPart]:
        """One part for each piece of text the upstream sends, then the end. Closing the
        generator closes the upstream's response, which stops the model."""
        body = self._body(messages, parameters) | {
            "stream": True,
            # The usage comes in a last chunk without choices.
            "stream_options": {"include_usage": True},
        }
        model, finish_reason, usage = self._model, None, None
        try:
            async with self._client.stream("POST", self._url, json=body) as response:
                if not response.is_success:
                    raise status_error(response.status_code, _json(await response.aread()))
                async for line in response.aiter_lines():
                    data = _data(line)
                    if data is None:
                        continue
                    if data == DONE:
                        break
                    chunk = _json(data)
                    if not isinstance(chunk, dict):
                        raise unreadable()
                    if "error" in chunk:
                        raise stream_error(chunk["error"])
                    model = _text(chunk.get("model")) or model
                    usage = _usage(chunk.get("usage")) or usage
                    choice = _first_choice(chunk)
                    if choice is None:
                        continue
                    finish_reason = _text(choice.get("finish_reason")) or finish_reason
                    delta = choice.get("delta")
                    if not isinstance(delta, dict):
                        continue
                    if reasoning := _reasoning(delta):
                        yield ReasoningDelta(text=reasoning)
                    if content := _text(delta.get("content")):
                        yield ContentDelta(text=content)
        except httpx2.HTTPError as error:
            raise transport_error(error) from error
        yield StreamEnd(model=model, finish_reason=finish_reason, usage=usage)

    async def is_ready(self) -> bool:
        """Try a completion of one token, as ai-bootstrap does: a server can list its model
        before it can serve it. A 400 counts as ready: the upstream answered, and refused only
        the probe's own `max_tokens`."""
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
        try:
            response = await self._client.post(
                self._url, json=body, timeout=self._readiness_timeout
            )
        except httpx2.HTTPError:
            return False
        return response.is_success or response.status_code == BAD_REQUEST

    async def aclose(self) -> None:
        await self._client.aclose()

    def _body(self, messages: Sequence[ChatMessage], parameters: Parameters) -> dict[str, Any]:
        # A request can't carry `model` or `messages` among its parameters: they're reserved.
        return {
            **parameters,
            "model": self._model,
            "messages": [message.model_dump() for message in messages],
        }


def _data(line: str) -> str | None:
    """A server-sent event's data, from its line; None for a blank line, a comment or another
    field."""
    if not line.startswith("data:"):
        return None
    return line[len("data:") :].removeprefix(" ")


def _json(text: str | bytes) -> object:
    """The text as JSON, or None when it isn't JSON."""
    try:
        return json.loads(text)
    except ValueError:
        return None


def _first_choice(body: object) -> dict[str, Any] | None:
    choices = body.get("choices") if isinstance(body, dict) else None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0]
    return None


def _text(value: object) -> str | None:
    """A non-empty string, or None."""
    return value if isinstance(value, str) and value else None


def _reasoning(holder: dict[str, Any]) -> str:
    """The reasoning a message or a delta carries, under whichever name the server uses."""
    for field in REASONING_FIELDS:
        if text := _text(holder.get(field)):
            return text
    return ""


def _whole(value: object) -> int | None:
    """A whole number, or None."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _usage(usage: object) -> Usage | None:
    """The three counts, when the upstream gives all three."""
    if not isinstance(usage, dict):
        return None
    prompt = _whole(usage.get("prompt_tokens"))
    completion = _whole(usage.get("completion_tokens"))
    total = _whole(usage.get("total_tokens"))
    if prompt is None or completion is None or total is None:
        return None
    return Usage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)
