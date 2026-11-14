"""oha's command and its output (spec/decisions/0018)."""

import json
from typing import Any

from bench import oha
from bench.workload import LLAMA_20, STREAM_20

# oha 1.16.0's output, cut to what the runner reads, with times in seconds.
OUTPUT: dict[str, Any] = {
    "summary": {
        "successRate": 1.0,
        "fastest": 0.2403,
        "slowest": 0.2679,
        "average": 0.2417369,
        "totalData": 2_594_000,
    },
    "latencyPercentiles": {"p10": 0.2407, "p50": 0.241343, "p95": 0.243347, "p99": 0.253711},
    "firstBytePercentiles": {"p50": 0.000726, "p95": 0.004366, "p99": 0.025031},
    "statusCodeDistribution": {"200": 2990, "503": 4},
    "errorDistribution": {"connection closed before message completed": 6},
}


def test_the_command_sends_the_workload_open_loop() -> None:
    command = oha.command(STREAM_20, "http://go-gin:8000/api/chat/stream")

    assert command == [
        *("/usr/local/bin/oha", "--no-tui", "--output-format", "json"),
        *("-z", "30s", "-w", "-q", "100", "--latency-correction", "-c", "96", "-t", "30s"),
        *("-m", "POST", "-T", "application/json"),
        *("-d", json.dumps(STREAM_20.body)),
        "http://go-gin:8000/api/chat/stream",
    ]


def test_the_warm_up_is_the_same_command_for_less_time() -> None:
    measured = oha.command(STREAM_20, "http://go-gin:8000/api/chat/stream")
    warmup = oha.command(STREAM_20, "http://go-gin:8000/api/chat/stream", warmup=True)

    assert warmup == [
        ("5s" if part == "30s" and measured[at - 1] == "-z" else part)
        for at, part in enumerate(measured)
    ]
    assert (oha.time_limit_s(STREAM_20), oha.time_limit_s(STREAM_20, warmup=True)) == (30, 5)


def test_one_at_a_time_is_a_count_of_requests_over_one_connection() -> None:
    command = oha.command(LLAMA_20, "http://go-gin:8000/api/chat/stream")
    warmup = oha.command(LLAMA_20, "http://go-gin:8000/api/chat/stream", warmup=True)

    assert command == [
        *("/usr/local/bin/oha", "--no-tui", "--output-format", "json"),
        *("-n", "30", "-c", "1", "--disable-keepalive", "-t", "30s"),
        *("-m", "POST", "-T", "application/json"),
        *("-d", json.dumps(LLAMA_20.body)),
        "http://go-gin:8000/api/chat/stream",
    ]
    assert warmup[4:8] == ["-n", "3", "-c", "1"]
    # Every request may take its whole timeout.
    assert (oha.time_limit_s(LLAMA_20), oha.time_limit_s(LLAMA_20, warmup=True)) == (900, 90)


def test_the_output_is_read_in_milliseconds() -> None:
    results = oha.parse(json.dumps(OUTPUT))

    assert results.latency_ms == {
        "min": 240.3,
        "mean": 241.737,
        "p50": 241.343,
        "p95": 243.347,
        "p99": 253.711,
        "max": 267.9,
    }
    assert results.first_byte_ms == {"p50": 0.726, "p95": 4.366, "p99": 25.031}
    assert results.raw == OUTPUT


def test_every_request_counts_answered_or_not() -> None:
    results = oha.parse(json.dumps(OUTPUT))

    described = results.described(STREAM_20)

    assert results.requests == 3000
    assert described["requests_due"] == 3000
    assert described["rate_per_s"] == 100.0
    assert described["rate_kept"] is True
    assert described["statuses"] == {"200": 2990, "503": 4}
    assert described["errors"] == {"connection closed before message completed": 6}


def test_a_rate_that_wasnt_kept_is_said() -> None:
    output = OUTPUT | {"statusCodeDistribution": {"200": 2969}, "errorDistribution": {}}

    described = oha.parse(json.dumps(output)).described(STREAM_20)

    assert described["rate_per_s"] < 99
    assert described["rate_kept"] is False


def test_no_answer_gives_no_times() -> None:
    output = OUTPUT | {
        "summary": {"fastest": None, "slowest": None, "average": None, "totalData": 0},
        "latencyPercentiles": {"p50": None, "p95": None, "p99": None},
        "firstBytePercentiles": {},
    }

    results = oha.parse(json.dumps(output))

    assert set(results.latency_ms.values()) == {None}
    assert results.first_byte_ms == {"p50": None, "p95": None, "p99": None}


def test_one_at_a_time_keeps_its_load_when_every_request_was_sent() -> None:
    thirty = OUTPUT | {"statusCodeDistribution": {"200": 29}, "errorDistribution": {"timeout": 1}}
    fewer = OUTPUT | {"statusCodeDistribution": {"200": 29}, "errorDistribution": {}}

    described = oha.parse(json.dumps(thirty)).described(LLAMA_20)

    assert (described["requests"], described["requests_due"], described["rate_kept"]) == (
        30,
        30,
        True,
    )
    assert "rate_per_s" not in described
    assert oha.parse(json.dumps(fewer)).described(LLAMA_20)["rate_kept"] is False


def all_good(answers: int, size: int) -> oha.Results:
    output = OUTPUT | {"statusCodeDistribution": {"200": answers}, "errorDistribution": {}}
    output["summary"] = OUTPUT["summary"] | {"totalData": size}
    return oha.parse(json.dumps(output))


def test_every_answer_is_whole_when_each_is_a_200_of_a_whole_answers_size() -> None:
    described = all_good(3000, 3000 * 865).described(STREAM_20, 865)

    assert (described["size_bytes"], described["answer_bytes"]) == (2_595_000, 865)
    assert described["complete"] is True


def test_a_200_with_a_short_body_isnt_a_whole_answer() -> None:
    # One stream of 3,000 ended early, with an `error` event: 200 all the same.
    assert all_good(3000, 3000 * 865 - 700).complete(865) is False


def test_a_failed_request_or_another_status_isnt_a_whole_answer() -> None:
    assert oha.parse(json.dumps(OUTPUT)).complete(865) is False
    assert oha.parse(json.dumps(OUTPUT)).described(STREAM_20)["complete"] is False


def test_without_a_known_size_the_statuses_decide() -> None:
    assert all_good(30, 12_345).described(LLAMA_20)["complete"] is True
