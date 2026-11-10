"""The workloads the runner sends (spec/decisions/0018)."""

from dataclasses import dataclass, field
from typing import Any

from bench.fake import FakeSettings

QUESTION = [{"role": "user", "content": "In one sentence, what is an LLM?"}]


@dataclass(frozen=True)
class Workload:
    """The same request, sent at a fixed arrival rate to a backend whose fake has these settings."""

    name: str
    path: str
    body: dict[str, Any]
    settings: FakeSettings
    # Requests a second, for `duration_s`, after `warmup_s` at the same rate that isn't counted.
    rate: int
    duration_s: int
    warmup_s: int
    # Far more than the rate needs, so no request waits for a free connection.
    connections: int
    method: str = field(default="POST")

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
            "settings": self.settings.environment(),
        }


# 20 tokens: the first at 50 ms, then one every 10 ms, so each stream is due to end at 240 ms and
# about 24 are open at once. The rate is provisional until plan step 3.2.
STREAM_20 = Workload(
    name="stream-20",
    path="/api/chat/stream",
    body={"messages": QUESTION, "parameters": {"max_tokens": 20}},
    settings=FakeSettings(first_token_ms=50, token_gap_ms=10),
    rate=100,
    duration_s=30,
    warmup_s=5,
    connections=256,
)
