"""The workloads the runner sends (spec/decisions/0018)."""

import math
from dataclasses import dataclass, field, replace
from typing import Any

from bench.fake import FakeSettings

CONNECTIONS_PER_OPEN = 4

QUESTION = [{"role": "user", "content": "In one sentence, what is an LLM?"}]


@dataclass(frozen=True)
class Workload:
    """The same request, sent at a fixed arrival rate to a backend whose fake has these settings."""

    name: str
    path: str
    body: dict[str, Any]
    settings: FakeSettings
    # When the fake is due to end each answer, in milliseconds.
    due_ms: int
    # Requests a second, for `duration_s`, after `warmup_s` at the same rate that isn't counted.
    rate: int
    duration_s: int
    warmup_s: int
    method: str = field(default="POST")

    @property
    def connections(self) -> int:
        """Four times the answers open at once while the backend keeps its pace. That's enough
        for no request to wait for one, and few enough for each to be reused within about a
        second, before any server's idle timeout (spec/decisions/0020)."""
        return math.ceil(CONNECTIONS_PER_OPEN * self.rate * self.due_ms / 1000)

    def at(self, rate: int) -> Workload:
        """The same workload at another rate."""
        return replace(self, rate=rate)

    def described(self) -> dict[str, Any]:
        """The workload, as a run's file records it."""
        return {
            "name": self.name,
            "method": self.method,
            "path": self.path,
            "body": self.body,
            "rate_per_s": self.rate,
            "duration_s": self.duration_s,
            "warmup_s": self.warmup_s,
            "connections": self.connections,
            "due_ms": self.due_ms,
            "settings": self.settings.environment(),
        }


# 20 tokens: the first at 50 ms, then one every 10 ms, so each stream is due to end at 240 ms, and
# about 24 are open at once at 100 requests a second.
STREAM_20 = Workload(
    name="stream-20",
    path="/api/chat/stream",
    body={"messages": QUESTION, "parameters": {"max_tokens": 20}},
    settings=FakeSettings(first_token_ms=50, token_gap_ms=10),
    due_ms=240,
    rate=100,
    duration_s=30,
    warmup_s=5,
)

# The rates the runner sends by default, in requests a second: provisional until plan step 3.2
# (spec/decisions/0020).
RATES = (100, 500, 1000, 2000)
