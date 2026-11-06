"""The in-process fake: the contract's tokens, at the contract's pace
(contract/README.md#the-fakes)."""

import re
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import TypeIs

from pydantic import JsonValue

from app.errors import SERVICE_ERRORS, ServiceError
from app.fake.clock import Clock, LoopClock
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

MODEL = "fake"

# A word, for `prompt_tokens`: a run of anything but a space, a tab, a line feed or a carriage
# return. A non-breaking space belongs to its word.
_WORD = re.compile(r"[^ \t\n\r]+")


@dataclass(frozen=True)
class _Answer:
    """What one request gets: how many tokens, how it ends, and where it fails, if it does."""

    reasoning_tokens: int
    answer_tokens: int
    finish_reason: str
    usage: Usage
    # The failure `fake_error` asks for, and the token it takes the place of.
    failure: ServiceError | None
    fails_at: int


class FakeLLMClient:
    """Answers with the contract's tokens, wrapping around, each at its time.

    Token i, counting the reasoning and the answer together, is due at
    start + FAKE_FIRST_TOKEN_MS + i * FAKE_TOKEN_GAP_MS. The start is the call.
    """

    def __init__(
        self, settings: Settings, tokens: Sequence[str], clock: Clock | None = None
    ) -> None:
        self._settings = settings
        self._tokens = tuple(tokens)
        self._clock = clock or LoopClock()

    async def complete(self, messages: Sequence[ChatMessage], parameters: Parameters) -> Completion:
        """The whole answer, at the last token's time."""
        start = self._clock.now()
        answer = self._answer(messages, parameters)
        if answer.failure is not None:
            await self._clock.sleep_until(self._due(start, answer.fails_at))
            raise answer.failure
        tokens = answer.reasoning_tokens + answer.answer_tokens
        await self._clock.sleep_until(self._due(start, tokens - 1))
        return Completion(
            content=self._text(answer.answer_tokens),
            reasoning=self._text(answer.reasoning_tokens) or None,
            model=MODEL,
            finish_reason=answer.finish_reason,
            usage=answer.usage,
        )

    async def stream(
        self, messages: Sequence[ChatMessage], parameters: Parameters
    ) -> AsyncGenerator[StreamPart]:
        """The reasoning, then the answer, a token at a time, then the end."""
        start = self._clock.now()
        answer = self._answer(messages, parameters)
        tokens = answer.reasoning_tokens + answer.answer_tokens
        for index in range(answer.fails_at if answer.failure is not None else tokens):
            await self._clock.sleep_until(self._due(start, index))
            if index < answer.reasoning_tokens:
                yield ReasoningDelta(text=self._token(index))
            else:
                yield ContentDelta(text=self._token(index - answer.reasoning_tokens))
        if answer.failure is not None:
            await self._clock.sleep_until(self._due(start, answer.fails_at))
            raise answer.failure
        yield StreamEnd(model=MODEL, finish_reason=answer.finish_reason, usage=answer.usage)

    async def is_ready(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None

    def _answer(self, messages: Sequence[ChatMessage], parameters: Parameters) -> _Answer:
        reasoning = self._settings.fake_reasoning_tokens
        length = self._settings.fake_answer_tokens
        limit = parameters.get("max_tokens")
        if _is_whole(limit) and 1 <= limit < length:
            answer, finish_reason = limit, "length"
        else:
            answer, finish_reason = length, "stop"
        prompt = sum(len(_WORD.findall(message.content)) for message in messages)
        failure, fails_at = _failure(parameters.get("fake_error"), reasoning + answer)
        return _Answer(
            reasoning_tokens=reasoning,
            answer_tokens=answer,
            finish_reason=finish_reason,
            usage=Usage(
                prompt_tokens=prompt,
                completion_tokens=reasoning + answer,
                total_tokens=prompt + reasoning + answer,
            ),
            failure=failure,
            fails_at=fails_at,
        )

    def _due(self, start: float, index: int) -> float:
        settings = self._settings
        return start + (settings.fake_first_token_ms + index * settings.fake_token_gap_ms) / 1000

    def _token(self, index: int) -> str:
        return self._tokens[index % len(self._tokens)]

    def _text(self, tokens: int) -> str:
        return "".join(self._token(index) for index in range(tokens))


def _is_whole(value: JsonValue) -> TypeIs[int]:
    """A JSON whole number: an int, but not a bool, which Python counts as one."""
    return isinstance(value, int) and not isinstance(value, bool)


def _failure(spec: JsonValue, tokens: int) -> tuple[ServiceError | None, int]:
    """The failure `fake_error` asks for, and the token it takes the place of. A malformed one
    fails at once, with 502, as an upstream refuses a parameter it doesn't accept."""
    if spec is None:
        return None, tokens
    if not isinstance(spec, dict):
        raise ServiceError("The fake refused fake_error: it must be an object")
    status = spec.get("status")
    after = spec.get("after_tokens", 0)
    if not _is_whole(status) or status not in SERVICE_ERRORS:
        raise ServiceError("The fake refused fake_error: status must be 429, 502, 503 or 504")
    if not _is_whole(after) or after < 0:
        raise ServiceError("The fake refused fake_error: after_tokens must be 0 or more")
    error = SERVICE_ERRORS[status](f"The fake failed with {status}, as fake_error asked")
    return error, min(after, tokens)
