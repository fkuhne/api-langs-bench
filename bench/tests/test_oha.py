"""oha's command and its output (spec/decisions/0018)."""

import json
from typing import Any

from bench import oha
from bench.workload import STREAM_20

# oha 1.16.0's output, cut to what the runner reads, with times in seconds.
OUTPUT: dict[str, Any] = {
    "summary": {"successRate": 1.0, "fastest": 0.2403, "slowest": 0.2679, "average": 0.2417369},
    "latencyPercentiles": {"p10": 0.2407, "p50": 0.241343, "p95": 0.243347, "p99": 0.253711},
    "firstBytePercentiles": {"p50": 0.000726, "p95": 0.004366, "p99": 0.025031},
    "statusCodeDistribution": {"200": 2990, "503": 4},
    "errorDistribution": {"connection closed before message completed": 6},
}


def test_the_command_sends_the_workload_open_loop() -> None:
    command = oha.command(STREAM_20, "http://go-gin:8000/api/chat/stream", 30)

    assert command == [
        *("/usr/local/bin/oha", "--no-tui", "--output-format", "json"),
        *("-z", "30s", "-w", "-q", "100", "--latency-correction", "-c", "96", "-t", "30s"),
        *("-m", "POST", "-T", "application/json"),
        *("-d", json.dumps(STREAM_20.body)),
        "http://go-gin:8000/api/chat/stream",
    ]


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
        "summary": {"fastest": None, "slowest": None, "average": None},
        "latencyPercentiles": {"p50": None, "p95": None, "p99": None},
        "firstBytePercentiles": {},
    }

    results = oha.parse(json.dumps(output))

    assert set(results.latency_ms.values()) == {None}
    assert results.first_byte_ms == {"p50": None, "p95": None, "p99": None}
