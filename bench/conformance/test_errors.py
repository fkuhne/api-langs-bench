"""Invalid bodies and the upstream's failures, at the default settings
(contract/README.md#errors, contract/README.md#errors-on-request)."""

import json
from typing import Any

import pytest

from bench.contract import Contract
from bench.fake import SERVICE_STATUSES
from conformance.helpers import HI, Check, Served, post

PATHS = ("/api/chat", "/api/chat/stream")


def asking(parameters: str) -> str:
    return '{"messages": [{"role": "user", "content": "Hi"}], "parameters": ' + parameters + "}"


INVALID_BODIES = {
    "not JSON": '{"messages": [',
    "no body": "",
    "a JSON list": "[1]",
    "no messages": "{}",
    "empty messages": '{"messages": []}',
    "null messages": '{"messages": null}',
    "messages not a list": '{"messages": {"role": "user", "content": "x"}}',
    "an unknown role": '{"messages": [{"role": "tool", "content": "x"}]}',
    "no role": '{"messages": [{"content": "x"}]}',
    "empty content": '{"messages": [{"role": "user", "content": ""}]}',
    "no content": '{"messages": [{"role": "user"}]}',
    "a number content": '{"messages": [{"role": "user", "content": 1}]}',
    "content parts": '{"messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}]}',
    "parameters as a list": asking("[1]"),
    "null parameters": asking("null"),
    **{
        f"the reserved key {key}": asking(json.dumps({key: True}))
        for key in ("model", "messages", "stream", "stream_options")
    },
}


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("body", INVALID_BODIES.values(), ids=INVALID_BODIES.keys())
def test_an_invalid_body_answers_422(defaults: Served, check: Check, path: str, body: str) -> None:
    check.json(post(defaults.client, path, body), 422, "ValidationError")


@pytest.mark.parametrize("after_tokens", [0, 2])
@pytest.mark.parametrize("status", SERVICE_STATUSES)
def test_an_upstream_failure_after_its_tokens(
    defaults: Served, check: Check, status: int, after_tokens: int
) -> None:
    fake_error = {"status": status, "after_tokens": after_tokens}

    check.answers(defaults, {"messages": HI, "parameters": {"fake_error": fake_error}})


def test_the_contracts_failing_request(defaults: Served, check: Check, contract: Contract) -> None:
    check.answers(defaults, contract.examples.failing_request)


def test_a_failure_after_a_short_answer_follows_all_of_it(defaults: Served, check: Check) -> None:
    parameters = {"max_tokens": 3, "fake_error": {"status": 504, "after_tokens": 10}}

    check.answers(defaults, {"messages": HI, "parameters": parameters})


MALFORMED: dict[str, Any] = {
    "an unknown status": {"status": 500},
    "a success": {"status": 200},
    "a string status": {"status": "503"},
    "a status that isn't whole": {"status": 503.0},
    "no status": {"after_tokens": 1},
    "a negative count": {"status": 503, "after_tokens": -1},
    "a count that isn't whole": {"status": 503, "after_tokens": 2.5},
    "a string count": {"status": 503, "after_tokens": "2"},
    "a null count": {"status": 503, "after_tokens": None},
    "a string": "503",
    "a list": [503],
}


@pytest.mark.parametrize("fake_error", MALFORMED.values(), ids=MALFORMED.keys())
def test_a_malformed_fake_error_fails_at_once_with_502(
    defaults: Served, check: Check, fake_error: Any
) -> None:
    check.answers(defaults, {"messages": HI, "parameters": {"fake_error": fake_error}})
