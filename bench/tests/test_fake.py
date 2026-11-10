"""The suite's model of the fakes says what the contract's page says (contract/README.md)."""

import json
from typing import Any

import pytest

from bench.contract import Contract
from bench.fake import REFUSED, FakeSettings, answer
from bench.sse import parse

CONTRACT = Contract()
TOKENS = CONTRACT.tokens
HI = [{"role": "user", "content": "Hi"}]


def answering(parameters: dict[str, Any], settings: FakeSettings | None = None) -> Any:
    return answer(settings or FakeSettings(), TOKENS, HI, parameters)


def test_the_pages_example_is_the_whole_answer() -> None:
    example = CONTRACT.examples.request

    got = answer(FakeSettings(), TOKENS, example["messages"], example["parameters"])

    assert got.completion() == CONTRACT.examples.completion


def test_the_pages_example_is_the_stream() -> None:
    example = CONTRACT.examples.request
    page = [(event.name, event.value()) for event in parse(CONTRACT.examples.stream)]

    got = answer(FakeSettings(), TOKENS, example["messages"], example["parameters"])

    assert got.events() == page


def test_the_pages_failing_request_makes_two_tokens_then_fails() -> None:
    example = CONTRACT.examples.failing_request

    got = answer(FakeSettings(), TOKENS, example["messages"], example["parameters"])

    assert [name for name, _ in got.events()] == ["token", "token", "error"]
    assert got.events()[-1] == ("error", {"status": 503})


def test_the_answer_wraps_around_after_the_last_token() -> None:
    got = answering({}, FakeSettings(answer_tokens=len(TOKENS) + 2))

    assert got.content[len(TOKENS) :] == TOKENS[:2]
    assert got.finish_reason == "stop"


def test_the_reasoning_and_the_answer_each_start_from_the_first_token() -> None:
    got = answering({}, FakeSettings(answer_tokens=3, reasoning_tokens=2))

    assert got.reasoning == TOKENS[:2]
    assert got.content == TOKENS[:3]
    assert got.usage == {"prompt_tokens": 1, "completion_tokens": 5, "total_tokens": 6}
    assert [name for name, _ in got.events()] == ["reasoning"] * 2 + ["token"] * 3 + ["done"]


def test_no_reasoning_is_null() -> None:
    assert answering({}).completion()["reasoning"] is None


@pytest.mark.parametrize(
    ("max_tokens", "length", "finish_reason"),
    [
        ("5", 5, "length"),
        ("1", 1, "length"),
        ("255", 255, "length"),
        ("256", 256, "stop"),
        ("300", 256, "stop"),
        ("0", 256, "stop"),
        ("-1", 256, "stop"),
        ("5.0", 256, "stop"),
        ("5e0", 256, "stop"),
        ('"5"', 256, "stop"),
        ("true", 256, "stop"),
        ("null", 256, "stop"),
        ("1" + "0" * 30, 256, "stop"),
        ("-1" + "0" * 30, 256, "stop"),
    ],
)
def test_only_a_smaller_positive_whole_number_cuts_the_answer(
    max_tokens: str, length: int, finish_reason: str
) -> None:
    got = answering({"max_tokens": json.loads(max_tokens)})

    assert (len(got.content), got.finish_reason) == (length, finish_reason)


@pytest.mark.parametrize(
    ("content", "words"),
    [
        ("Hi", 1),
        ("  two   words  ", 2),
        ("a\tb\nc\rd\r\ne", 5),
        ("a\N{NO-BREAK SPACE}b c", 2),
        ("a\N{EM SPACE}b\N{IDEOGRAPHIC SPACE}c\N{NEXT LINE}d\x0be\x0cf", 1),
    ],
)
def test_prompt_tokens_count_words_split_by_four_characters(content: str, words: int) -> None:
    got = answer(FakeSettings(), TOKENS, [{"role": "user", "content": content}], {})

    assert got.usage["prompt_tokens"] == words


def test_prompt_tokens_count_every_message() -> None:
    messages = [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Hi there"},
        {"role": "assistant", "content": "Hello."},
    ]

    got = answer(FakeSettings(answer_tokens=3), TOKENS, messages, {})

    assert got.usage == {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}


def test_the_whole_answer_is_due_at_the_last_tokens_time() -> None:
    settings = FakeSettings(
        answer_tokens=4, reasoning_tokens=1, first_token_ms=100, token_gap_ms=20
    )

    assert answering({}, settings).due_ms == 100 + 4 * 20


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_a_failure_takes_the_place_of_the_next_token(status: int) -> None:
    settings = FakeSettings(
        answer_tokens=5, reasoning_tokens=1, first_token_ms=100, token_gap_ms=20
    )

    got = answering({"fake_error": {"status": status, "after_tokens": 2}}, settings)

    assert got.events() == [
        ("reasoning", {"text": TOKENS[0]}),
        ("token", {"text": TOKENS[0]}),
        ("error", {"status": status}),
    ]
    assert got.due_ms == 100 + 2 * 20


def test_a_failure_with_no_count_comes_first() -> None:
    got = answering({"fake_error": {"status": 429}}, FakeSettings(first_token_ms=50))

    assert got.events() == [("error", {"status": 429})]
    assert got.due_ms == 50


def test_a_failure_after_a_short_answer_follows_all_of_it() -> None:
    settings = FakeSettings(first_token_ms=10, token_gap_ms=5)

    got = answering({"max_tokens": 3, "fake_error": {"status": 504, "after_tokens": 10}}, settings)

    assert [name for name, _ in got.events()] == ["token"] * 3 + ["error"]
    assert got.due_ms == 10 + 3 * 5


@pytest.mark.parametrize(
    "fake_error",
    [
        pytest.param({"status": 500}, id="an unknown status"),
        pytest.param({"status": 200}, id="a success"),
        pytest.param({"status": "503"}, id="a string status"),
        pytest.param({"status": 503.0}, id="a status that isn't whole"),
        pytest.param({"after_tokens": 1}, id="no status"),
        pytest.param({"status": 503, "after_tokens": -1}, id="a negative count"),
        pytest.param({"status": 503, "after_tokens": 2.5}, id="a count that isn't whole"),
        pytest.param({"status": 503, "after_tokens": "2"}, id="a string count"),
        pytest.param({"status": 503, "after_tokens": None}, id="a null count"),
        pytest.param("503", id="a string"),
        pytest.param([503], id="a list"),
    ],
)
def test_a_malformed_fake_error_fails_at_once_with_502(fake_error: Any) -> None:
    got = answering({"fake_error": fake_error}, FakeSettings(first_token_ms=100))

    assert got.events() == [("error", {"status": REFUSED})]
    assert got.due_ms == 0


def test_the_settings_are_the_backends_environment() -> None:
    settings = FakeSettings(
        answer_tokens=40, reasoning_tokens=2, first_token_ms=100, token_gap_ms=20
    )

    assert settings.environment() == {
        "LLM_PROVIDER": "fake",
        "FAKE_ANSWER_TOKENS": "40",
        "FAKE_REASONING_TOKENS": "2",
        "FAKE_FIRST_TOKEN_MS": "100",
        "FAKE_TOKEN_GAP_MS": "20",
    }
