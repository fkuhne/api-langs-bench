"""What the fakes answer, worked out from the contract's rules (contract/README.md#the-fakes).

This is the conformance suite's own model of the fakes, written from the contract's page, not
from any backend. The suite compares each backend's answers with it.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeIs

MODEL = "fake"
# The statuses an upstream's failure takes (contract/README.md#errors).
SERVICE_STATUSES = (429, 502, 503, 504)
# A malformed `fake_error` fails at once with this status.
REFUSED = 502

# A word, for `prompt_tokens`: a run of anything but a space, a tab, a line feed or a carriage
# return.
_WORD = re.compile(r"[^ \t\n\r]+")


@dataclass(frozen=True)
class FakeSettings:
    """The fakes' settings (contract/README.md#settings). The defaults are the contract's."""

    answer_tokens: int = 256
    reasoning_tokens: int = 0
    first_token_ms: int = 0
    token_gap_ms: int = 0

    def environment(self) -> dict[str, str]:
        """Every setting, as the backends read it from their environment."""
        return {
            "LLM_PROVIDER": "fake",
            "FAKE_ANSWER_TOKENS": str(self.answer_tokens),
            "FAKE_REASONING_TOKENS": str(self.reasoning_tokens),
            "FAKE_FIRST_TOKEN_MS": str(self.first_token_ms),
            "FAKE_TOKEN_GAP_MS": str(self.token_gap_ms),
        }

    def due_ms(self, index: int) -> int:
        """When token `index` is due, counting the reasoning and the answer together, in
        milliseconds from the start."""
        return self.first_token_ms + index * self.token_gap_ms


@dataclass(frozen=True)
class Answer:
    """What the fakes answer one request."""

    reasoning: tuple[str, ...]
    content: tuple[str, ...]
    finish_reason: str
    usage: dict[str, int]
    # The status `fake_error` asks for, and the token it takes the place of; None for no failure.
    failure: int | None
    fails_at: int
    # When the failure comes, or the whole answer, in milliseconds from the start.
    due_ms: int

    def completion(self) -> dict[str, Any]:
        """The whole answer's body, from `POST /api/chat`, when it doesn't fail."""
        return {
            "content": "".join(self.content),
            "reasoning": "".join(self.reasoning) or None,
            "model": MODEL,
            "finish_reason": self.finish_reason,
            "usage": self.usage,
        }

    def events(self) -> list[tuple[str, dict[str, Any]]]:
        """The stream's events, by name and data. An `error` event's data is only its status,
        since its `detail` is never compared."""
        pieces = [("reasoning", {"text": text}) for text in self.reasoning]
        pieces += [("token", {"text": text}) for text in self.content]
        if self.failure is not None:
            return [*pieces[: self.fails_at], ("error", {"status": self.failure})]
        end = {"model": MODEL, "finish_reason": self.finish_reason, "usage": self.usage}
        return [*pieces, ("done", end)]


def answer(
    settings: FakeSettings,
    tokens: Sequence[str],
    messages: Sequence[Mapping[str, Any]],
    parameters: Mapping[str, Any],
) -> Answer:
    """What the fakes answer these messages and parameters, with these settings and tokens."""
    length = settings.answer_tokens
    limit = parameters.get("max_tokens")
    if is_whole(limit) and 1 <= limit < length:
        length, finish_reason = limit, "length"
    else:
        finish_reason = "stop"
    reasoning = settings.reasoning_tokens
    made = reasoning + length
    prompt = sum(len(_WORD.findall(message["content"])) for message in messages)
    failure, fails_at = _failure(parameters.get("fake_error"), made)
    if failure is None:
        due_ms = settings.due_ms(made - 1)
    elif fails_at < 0:
        failure, fails_at, due_ms = REFUSED, 0, 0
    else:
        due_ms = settings.due_ms(fails_at)
    return Answer(
        reasoning=tuple(_token(tokens, index) for index in range(reasoning)),
        content=tuple(_token(tokens, index) for index in range(length)),
        finish_reason=finish_reason,
        usage={
            "prompt_tokens": prompt,
            "completion_tokens": made,
            "total_tokens": prompt + made,
        },
        failure=failure,
        fails_at=fails_at,
        due_ms=due_ms,
    )


def is_whole(value: object) -> TypeIs[int]:
    """A JSON whole number, as Python's `json` reads one: `5`, but not `5.0`, `5e0`, `"5"` or
    `true`."""
    return isinstance(value, int) and not isinstance(value, bool)


def _token(tokens: Sequence[str], index: int) -> str:
    """Each text starts from the first token, and wraps around after the last."""
    return tokens[index % len(tokens)]


def _failure(spec: Any, made: int) -> tuple[int | None, int]:
    """The status `fake_error` asks for, and the token whose place it takes; (502, -1) for a
    malformed one, which fails at once. No `fake_error` is no failure."""
    if spec is None:
        return None, made
    if not isinstance(spec, dict):
        return REFUSED, -1
    status = spec.get("status")
    after = spec.get("after_tokens", 0)
    if not is_whole(status) or status not in SERVICE_STATUSES:
        return REFUSED, -1
    if not is_whole(after) or after < 0:
        return REFUSED, -1
    return status, min(after, made)
