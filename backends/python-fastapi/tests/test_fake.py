"""The fake keeps the contract's rules (contract/README.md#the-fakes)."""

from typing import Any

import pytest

from app.errors import ServiceError, ServiceUnavailableError
from app.fake.client import FakeLLMClient
from app.fake.tokens import load_tokens
from app.llm.port import (
    ChatMessage,
    ContentDelta,
    Parameters,
    ReasoningDelta,
    StreamEnd,
    Usage,
)
from app.settings import Settings
from tests.helpers import FakeClock

pytestmark = pytest.mark.anyio

TOKENS = load_tokens()
QUESTION = [ChatMessage(role="user", content="In one sentence, what is an LLM?")]


def fake_with(clock: FakeClock, **settings: Any) -> FakeLLMClient:
    return FakeLLMClient(Settings(**settings), TOKENS, clock)


async def parts(fake: FakeLLMClient, parameters: Parameters) -> list[Any]:
    return [part async for part in fake.stream(QUESTION, parameters)]


async def test_max_tokens_cuts_the_answer(fake: FakeLLMClient) -> None:
    *answer, end = await parts(fake, {"max_tokens": 5})

    assert [part.text for part in answer] == list(TOKENS[:5])
    assert all(isinstance(part, ContentDelta) for part in answer)
    assert end == StreamEnd(
        model="fake",
        finish_reason="length",
        usage=Usage(prompt_tokens=7, completion_tokens=5, total_tokens=12),
    )


@pytest.mark.parametrize("max_tokens", [None, 3, 4, 0, -1, "2", 2.5, True])
async def test_the_answer_is_fake_answer_tokens_long_otherwise(
    clock: FakeClock, max_tokens: Any
) -> None:
    *answer, end = await parts(fake_with(clock, fake_answer_tokens=3), {"max_tokens": max_tokens})

    assert len(answer) == 3
    assert end.finish_reason == "stop"


async def test_the_tokens_wrap_around(clock: FakeClock) -> None:
    *answer, _ = await parts(fake_with(clock, fake_answer_tokens=len(TOKENS) + 2), {})

    assert [part.text for part in answer[-2:]] == list(TOKENS[:2])


async def test_reasoning_comes_first_and_counts_as_completion(clock: FakeClock) -> None:
    fake = fake_with(clock, fake_reasoning_tokens=2, fake_answer_tokens=3)

    *pieces, end = await parts(fake, {"max_tokens": 1})
    whole = await fake.complete(QUESTION, {"max_tokens": 1})

    assert [type(piece) for piece in pieces] == [ReasoningDelta, ReasoningDelta, ContentDelta]
    assert [piece.text for piece in pieces] == [TOKENS[0], TOKENS[1], TOKENS[0]]
    assert end.usage.completion_tokens == 3
    assert (whole.reasoning, whole.content) == (TOKENS[0] + TOKENS[1], TOKENS[0])


async def test_without_reasoning_the_whole_answer_has_none(fake: FakeLLMClient) -> None:
    whole = await fake.complete(QUESTION, {"max_tokens": 5})

    assert whole.reasoning is None
    assert whole.content == "A backend in front of"


async def test_each_token_waits_for_its_own_time(clock: FakeClock) -> None:
    fake = fake_with(clock, fake_first_token_ms=100, fake_token_gap_ms=20)
    clock.time = 50.0

    await parts(fake, {"max_tokens": 4})

    assert clock.waits == pytest.approx([50.1, 50.12, 50.14, 50.16])


async def test_the_whole_answer_waits_once_for_the_last_token(clock: FakeClock) -> None:
    fake = fake_with(clock, fake_first_token_ms=100, fake_token_gap_ms=20)

    await fake.complete(QUESTION, {"max_tokens": 4})

    assert clock.waits == pytest.approx([0.16])


async def test_fake_error_fails_in_place_of_the_next_token(clock: FakeClock) -> None:
    fake = fake_with(clock, fake_first_token_ms=100, fake_token_gap_ms=20)
    stream = fake.stream(QUESTION, {"fake_error": {"status": 503, "after_tokens": 2}})

    made = [await anext(stream), await anext(stream)]
    with pytest.raises(ServiceUnavailableError):
        await anext(stream)

    assert [part.text for part in made if isinstance(part, ContentDelta)] == list(TOKENS[:2])
    assert clock.waits == pytest.approx([0.1, 0.12, 0.14])


async def test_fake_error_fails_the_whole_answer_at_the_same_time(clock: FakeClock) -> None:
    fake = fake_with(clock, fake_first_token_ms=100, fake_token_gap_ms=20)

    with pytest.raises(ServiceUnavailableError):
        await fake.complete(QUESTION, {"fake_error": {"status": 503, "after_tokens": 2}})

    assert clock.waits == pytest.approx([0.14])


async def test_fake_error_after_the_last_token_still_fails(clock: FakeClock) -> None:
    fake = fake_with(clock, fake_answer_tokens=2)
    stream = fake.stream(QUESTION, {"fake_error": {"status": 429, "after_tokens": 9}})

    made = [await anext(stream), await anext(stream)]
    with pytest.raises(ServiceError) as raised:
        await anext(stream)

    assert len(made) == 2
    assert raised.value.status_code == 429


@pytest.mark.parametrize(
    "spec",
    [
        pytest.param("503", id="not an object"),
        pytest.param({"status": 500}, id="an unknown status"),
        pytest.param({"status": True}, id="a bool status"),
        pytest.param({"status": 503, "after_tokens": -1}, id="negative after_tokens"),
        pytest.param({"status": 503, "after_tokens": 1.5}, id="fractional after_tokens"),
    ],
)
async def test_a_malformed_fake_error_fails_at_once_with_502(clock: FakeClock, spec: Any) -> None:
    fake = fake_with(clock, fake_first_token_ms=100)

    with pytest.raises(ServiceError) as raised:
        await anext(fake.stream(QUESTION, {"fake_error": spec}))

    assert type(raised.value) is ServiceError
    assert raised.value.status_code == 502
    assert clock.waits == []


async def test_a_null_fake_error_is_no_error(fake: FakeLLMClient) -> None:
    *_, end = await parts(fake, {"fake_error": None, "max_tokens": 1})

    assert isinstance(end, StreamEnd)


async def test_words_split_on_four_characters_only(fake: FakeLLMClient) -> None:
    messages = [
        ChatMessage(role="system", content="one\ttwo\nthree\r\nfour  five"),
        ChatMessage(role="user", content="non\u00a0breaking space"),
    ]

    whole = await fake.complete(messages, {"max_tokens": 1})

    assert whole.usage is not None
    assert whole.usage.prompt_tokens == 7


async def test_the_fake_is_always_ready(fake: FakeLLMClient) -> None:
    assert await fake.is_ready()
    await fake.aclose()
