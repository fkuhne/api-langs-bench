"""oha, the load generator: its command, and what it measured (spec/decisions/0018).

For a workload at a rate, oha sends at that rate, whatever the backend does, and counts each
request's latency from when it was due to be sent. For one request at a time, it sends each when
the last has ended (spec/decisions/0026).
"""

import json
from dataclasses import dataclass
from typing import Any

from bench.workload import Load, OneAtATime, Workload

# Where the runner's image puts oha's binary.
OHA = "/usr/local/bin/oha"
# A request with no answer after this long is counted as an error, so a stuck backend can't hold
# a run for ever.
REQUEST_TIMEOUT_S = 30
# The share of the requests due that must be sent for the rate to count as kept.
RATE_KEPT = 0.99

_PERCENTILES = ("p50", "p95", "p99")


def command(load: Load, url: str, *, warmup: bool = False) -> list[str]:
    """oha's command for `load` against `url`: its warm-up, or what's measured."""
    if isinstance(load, Workload):
        how = [
            *("-z", f"{load.warmup_s if warmup else load.duration_s}s"),
            # Requests open at the end are waited for, not cut.
            "-w",
            *("-q", str(load.rate)),
            "--latency-correction",
            *("-c", str(load.connections)),
        ]
    else:
        how = [
            *("-n", str(load.warmup_requests if warmup else load.requests)),
            *("-c", "1"),
            # A new connection for each request. llama.cpp closes its connection after a stream,
            # and oha counts the next request on it as failed (spec/decisions/0026).
            "--disable-keepalive",
        ]
    return [
        OHA,
        "--no-tui",
        *("--output-format", "json"),
        *how,
        *("-t", f"{REQUEST_TIMEOUT_S}s"),
        *("-m", load.method),
        *("-T", "application/json"),
        *("-d", json.dumps(load.body)),
        url,
    ]


def time_limit_s(load: Load, *, warmup: bool = False) -> int:
    """How long oha's command may take at most, before any grace: the time it sends for, or
    every request timing out in turn."""
    if isinstance(load, Workload):
        return load.warmup_s if warmup else load.duration_s
    return (load.warmup_requests if warmup else load.requests) * REQUEST_TIMEOUT_S


@dataclass(frozen=True)
class Results:
    """What oha measured in one go."""

    # Every request that got an answer, by its status, and every one that didn't, by its error.
    statuses: dict[str, int]
    errors: dict[str, int]
    # The whole response's latency, from when each request was due, and the time to its first
    # byte, from when it was sent. A time is None when no request gave one.
    latency_ms: dict[str, float | None]
    first_byte_ms: dict[str, float | None]
    # The bytes of every answer's body, together.
    size: int
    # oha's whole output.
    raw: dict[str, Any]

    @property
    def requests(self) -> int:
        return sum(self.statuses.values()) + sum(self.errors.values())

    def complete(self, answer_bytes: int | None) -> bool:
        """Whether every request got a whole answer: a 200, and a body of the size a whole answer
        has, when that's known. A stream answers 200 even when its upstream fails, with an
        `error` event in a short body, so the status alone doesn't say (spec/decisions/0026)."""
        if self.errors or set(self.statuses) != {"200"}:
            return False
        return answer_bytes is None or self.size == self.requests * answer_bytes

    def described(self, load: Load, answer_bytes: int | None = None) -> dict[str, Any]:
        """The results, as a run's file records them. One request at a time has no rate to keep:
        its load is kept when every request was sent. `answer_bytes` is a whole answer's size,
        when every answer has the same."""
        pace: dict[str, Any]
        if isinstance(load, OneAtATime):
            pace = {"requests_due": load.requests, "rate_kept": self.requests >= load.requests}
        else:
            due = load.rate * load.duration_s
            pace = {
                "requests_due": due,
                "rate_per_s": self.requests / load.duration_s,
                "rate_kept": self.requests >= RATE_KEPT * due,
            }
        return {
            "requests": self.requests,
            **pace,
            "statuses": self.statuses,
            "errors": self.errors,
            "size_bytes": self.size,
            "answer_bytes": answer_bytes,
            "complete": self.complete(answer_bytes),
            "latency_ms": self.latency_ms,
            "first_byte_ms": self.first_byte_ms,
        }


def parse(output: str) -> Results:
    """oha's JSON output, with its times in milliseconds."""
    raw: dict[str, Any] = json.loads(output)
    summary = raw["summary"]
    return Results(
        statuses=dict(raw["statusCodeDistribution"]),
        errors=dict(raw["errorDistribution"]),
        latency_ms={
            "min": _ms(summary["fastest"]),
            "mean": _ms(summary["average"]),
            **_percentiles(raw["latencyPercentiles"]),
            "max": _ms(summary["slowest"]),
        },
        first_byte_ms=_percentiles(raw["firstBytePercentiles"]),
        size=summary["totalData"],
        raw=raw,
    )


def _percentiles(seconds: dict[str, float | None]) -> dict[str, float | None]:
    return {name: _ms(seconds.get(name)) for name in _PERCENTILES}


def _ms(seconds: float | None) -> float | None:
    """Milliseconds, to the microsecond; None when no request gave a time."""
    return None if seconds is None else round(seconds * 1000, 3)
