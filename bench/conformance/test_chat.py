"""The whole answer and the stream, at the contract's default settings (contract/README.md)."""

import pytest

from bench.contract import Contract
from bench.sse import parse
from conformance.helpers import HI, Check, Served, normalized, post, stream


def test_the_contracts_example(defaults: Served, check: Check, contract: Contract) -> None:
    response = post(defaults.client, "/api/chat", contract.examples.request)

    got = check.json(response, 200, "Completion")

    # The page's example is the in-process fake's; the fake server names its own model.
    assert normalized(got) == normalized(contract.examples.completion | {"model": defaults.model})


def test_the_contracts_example_streamed(defaults: Served, check: Check, contract: Contract) -> None:
    page = [(event.name, event.value()) for event in parse(contract.examples.stream)]

    got = check.events(stream(defaults.client, contract.examples.request))

    *pieces, (done, end) = [(name, normalized(data)) for name, data in page]
    assert got == [*pieces, (done, end | {"model": defaults.model})]


def test_the_answer_wraps_around_after_the_last_token(defaults: Served, check: Check) -> None:
    # 256 tokens by default, past the file's 175.
    check.answers(defaults, {"messages": HI})


@pytest.mark.parametrize(
    "max_tokens",
    [
        "5",
        "1",
        "255",
        "256",
        "300",
        "0",
        "-1",
        "5.0",
        "5e0",
        '"5"',
        "true",
        "null",
        "1" + "0" * 30,
        "-1" + "0" * 30,
    ],
)
def test_only_a_smaller_positive_whole_number_cuts_the_answer(
    defaults: Served, check: Check, max_tokens: str
) -> None:
    body = '{"messages": [{"role": "user", "content": "Hi"}], "parameters": {"max_tokens": %s}}'

    check.answers(defaults, body % max_tokens)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("  two   words  ", id="runs of spaces"),
        pytest.param("a\tb\nc\rd\r\ne", id="tabs, line feeds and carriage returns"),
        pytest.param("a\N{NO-BREAK SPACE}b c", id="a non-breaking space"),
        pytest.param(
            "a\N{EM SPACE}b\N{IDEOGRAPHIC SPACE}c\N{NEXT LINE}d\x0be\x0cf",
            id="other white space",
        ),
    ],
)
def test_prompt_tokens_count_words_split_by_four_characters(
    defaults: Served, check: Check, content: str
) -> None:
    check.answers(defaults, {"messages": [{"role": "user", "content": content}]})


def test_prompt_tokens_count_every_message(defaults: Served, check: Check) -> None:
    messages = [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Hi there"},
        {"role": "assistant", "content": "Hello."},
        {"role": "user", "content": "And again?"},
    ]

    check.answers(defaults, {"messages": messages, "parameters": {"max_tokens": 3}})


def test_other_fields_and_parameters_are_ignored(defaults: Served, check: Check) -> None:
    messages = [{"role": "user", "content": "Hi", "name": "x"}]
    parameters = {"max_tokens": 4, "temperature": 0.2, "seed": 1, "stop": ["\n"]}

    check.answers(defaults, {"messages": messages, "parameters": parameters, "other": 1})


def test_the_stream_ends_as_the_whole_answer_does(defaults: Served, check: Check) -> None:
    body = {"messages": HI, "parameters": {"max_tokens": 7}}
    whole = check.json(post(defaults.client, "/api/chat", body), 200, "Completion")

    (*_, (name, end)) = check.events(stream(defaults.client, body))

    assert name == "done"
    assert end == normalized({key: whole.get(key) for key in ("model", "finish_reason", "usage")})
