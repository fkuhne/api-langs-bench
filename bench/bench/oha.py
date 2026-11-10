"""oha, the load generator: its command, and what it measured (spec/decisions/0018).

oha sends at a fixed rate, whatever the backend does, and counts each request's latency from when
it was due to be sent.
"""

import json
from dataclasses import dataclass
from typing import Any

from bench.workload import Workload

# Where the runner's image puts oha's binary.
OHA = "/usr/local/bin/oha"
# A request with no answer after this long is counted as an error, so a stuck backend can't hold
# a run for ever.
REQUEST_TIMEOUT_S = 30
# The share of the requests due that must be sent for the rate to count as kept.
RATE_KEPT = 0.99

_PERCENTILES = ("p50", "p95", "p99")


def command(workload: Workload, url: str, duration_s: int) -> list[str]:
    """oha's command for `duration_s` of `workload` against `url`."""
    return [
        OHA,
        "--no-tui",
        *("--output-format", "json"),
        *("-z", f"{duration_s}s"),
        # Requests open at the end are waited for, not cut.
        "-w",
        *("-q", str(workload.rate)),
        "--latency-correction",
        *("-c", str(workload.connections)),
        *("-t", f"{REQUEST_TIMEOUT_S}s"),
        *("-m", workload.method),
        *("-T", "application/json"),
        *("-d", json.dumps(workload.body)),
        url,
    ]


@dataclass(frozen=True)
class Results:
    """What oha measured in one go."""

    # Every request that got an answer, by its status, and every one that didn't, by its error.
    statuses: dict[str, int]
    errors: dict[str, int]
    # The whole response's latency, from when each request was due, and the time to its first byte.
    # A time is None when no request gave one.
    latency_ms: dict[str, float | None]
    first_byte_ms: dict[str, float | None]
    # oha's whole output.
    raw: dict[str, Any]

    @property
    def requests(self) -> int:
        return sum(self.statuses.values()) + sum(self.errors.values())

    def described(self, workload: Workload) -> dict[str, Any]:
        """The results, as a run's file records them."""
        due = workload.rate * workload.duration_s
        return {
            "requests": self.requests,
            "requests_due": due,
            "rate_per_s": self.requests / workload.duration_s,
            "rate_kept": self.requests >= RATE_KEPT * due,
            "statuses": self.statuses,
            "errors": self.errors,
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
        raw=raw,
    )


def _percentiles(seconds: dict[str, float | None]) -> dict[str, float | None]:
    return {name: _ms(seconds.get(name)) for name in _PERCENTILES}


def _ms(seconds: float | None) -> float | None:
    """Milliseconds, to the microsecond; None when no request gave a time."""
    return None if seconds is None else round(seconds * 1000, 3)
