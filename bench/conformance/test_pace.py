"""The fake's pace, measured from outside the backend, by the rule in spec/decisions/0017.

The backend runs a paced fake that reasons first: its first token at 100 ms, then one every
20 ms (`conftest.PACED`). Each check also holds the answer to the contract, as at the defaults.
"""

import time

import pytest

from bench.pace import Pace, Tolerance, lateness_ms
from conformance.helpers import HI, Backend, Body, Check, Served, expected_events, post, stream

# How many times a single timed event is asked for: its median is what's checked.
REPEATS = 5


def test_the_reasoning_comes_first(paced: Served, check: Check) -> None:
    check.answers(paced, {"messages": HI, "parameters": {"max_tokens": 5}})


def test_the_whole_answer_with_its_reasoning(paced: Served, check: Check) -> None:
    check.answers(paced, {"messages": HI})


def test_the_stream_keeps_the_pace(
    paced: Served, check: Check, tolerance: Tolerance, backend: Backend, report: list[str]
) -> None:
    body = {"messages": HI}
    streamed = stream(paced.client, body)
    expected = paced.expect(body, check.tokens)
    assert check.events(streamed) == expected_events(expected)
    pieces = streamed.events[:-1]
    due = [paced.settings.due_ms(index) for index in range(len(pieces))]

    pace = Pace(tuple(lateness_ms(streamed.sent, [event.at for event in pieces], due)))
    headers_ms = (streamed.headers_at - streamed.sent) / 1e6

    report.append(
        f"{backend.service}: {len(pieces)} events, lateness median {pace.median_ms:.2f} ms, "
        f"min {min(pace.lateness_ms):.2f}, max {max(pace.lateness_ms):.2f}; "
        f"the last quarter {pace.drift_ms or 0:+.2f} ms on the first; "
        f"headers at {headers_ms:.1f} ms"
    )
    assert headers_ms < due[0], "the headers waited for the first token"
    assert pace.problems(tolerance) == []


def timed(served: Served, path: str, body: Body, check: Check) -> float:
    """When the answer came, in milliseconds after the request went: the whole body, or the
    stream's last event."""
    if path == "/api/chat/stream":
        streamed = stream(served.client, body)
        assert check.events(streamed)
        return (streamed.events[-1].at - streamed.sent) / 1e6
    sent = time.perf_counter_ns()
    post(served.client, path, body).read()
    return (time.perf_counter_ns() - sent) / 1e6


def repeated(served: Served, path: str, body: Body, check: Check, tolerance: Tolerance) -> Pace:
    """The answer's lateness, asked for `REPEATS` times, after checking it once."""
    check.answers(served, body)
    due = served.expect(body, check.tokens).due_ms
    pace = Pace(tuple(timed(served, path, body, check) - due for _ in range(REPEATS)))
    assert pace.problems(tolerance, drift=False) == []
    return pace


def test_the_whole_answer_comes_at_the_last_tokens_time(
    paced: Served, check: Check, tolerance: Tolerance
) -> None:
    # 2 reasoning tokens and 3 answer tokens: the last is due at 180 ms.
    repeated(
        paced, "/api/chat", {"messages": HI, "parameters": {"max_tokens": 3}}, check, tolerance
    )


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/stream"])
def test_a_failure_comes_at_its_tokens_time(
    paced: Served, check: Check, tolerance: Tolerance, path: str
) -> None:
    # It takes the place of the fourth token, due at 160 ms.
    fake_error = {"status": 503, "after_tokens": 3}

    repeated(
        paced, path, {"messages": HI, "parameters": {"fake_error": fake_error}}, check, tolerance
    )


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/stream"])
def test_a_malformed_fake_error_fails_at_once(
    paced: Served, check: Check, tolerance: Tolerance, path: str
) -> None:
    fake_error = {"status": 500}

    repeated(
        paced, path, {"messages": HI, "parameters": {"fake_error": fake_error}}, check, tolerance
    )
