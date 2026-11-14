"""The workloads the runner sends (spec/decisions/0018, spec/decisions/0026)."""

import math
from dataclasses import dataclass, field, replace
from typing import Any

from bench.fake import FakeSettings

CONNECTIONS_PER_OPEN = 4

QUESTION = [{"role": "user", "content": "In one sentence, what is an LLM?"}]

# Where an upstream takes a chat request, and the model a backend asks it for by default
# (contract/README.md#the-upstream).
UPSTREAM_PATH = "/v1/chat/completions"
UPSTREAM_MODEL = "local"


def upstream_body(body: dict[str, Any], *, stream: bool) -> dict[str, Any]:
    """The request a backend's upstream client sends for `body`, so the same load can go straight
    to the upstream (contract/README.md#the-upstream)."""
    sent = {**body.get("parameters", {}), "model": UPSTREAM_MODEL, "messages": body["messages"]}
    if stream:
        sent |= {"stream": True, "stream_options": {"include_usage": True}}
    return sent


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

    @property
    def label(self) -> str:
        """The load, for a run's name."""
        return f"{self.rate}rps"

    @property
    def environment(self) -> dict[str, str]:
        """The fakes' settings this workload needs."""
        return self.settings.environment()

    def at(self, rate: int) -> Workload:
        """The same workload at another rate."""
        return replace(self, rate=rate)

    def alone(self) -> Workload:
        """The same load, as a backend sends it to its upstream, for a run of the upstream
        alone."""
        stream = self.path.endswith("/stream")
        return replace(self, path=UPSTREAM_PATH, body=upstream_body(self.body, stream=stream))

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


@dataclass(frozen=True)
class OneAtATime:
    """The same request, sent again each time the last has ended: a closed loop, for an upstream
    whose own time is most of the answer's, such as a real model (spec/decisions/0026)."""

    name: str
    path: str
    body: dict[str, Any]
    # How many requests are measured, after `warmup_requests` that aren't counted.
    requests: int
    warmup_requests: int
    method: str = field(default="POST")

    @property
    def label(self) -> str:
        """The load, for a run's name."""
        return f"{self.requests}x1"

    @property
    def environment(self) -> dict[str, str]:
        """No fake's settings: the upstream is a real model."""
        return {}

    def alone(self) -> OneAtATime:
        """The same load, as a backend sends it to its upstream, for a run of the upstream
        alone."""
        stream = self.path.endswith("/stream")
        return replace(self, path=UPSTREAM_PATH, body=upstream_body(self.body, stream=stream))

    def described(self) -> dict[str, Any]:
        """The workload, as a run's file records it."""
        return {
            "name": self.name,
            "method": self.method,
            "path": self.path,
            "body": self.body,
            "requests": self.requests,
            "warmup_requests": self.warmup_requests,
            # One request at a time, each on a connection of its own.
            "connections": 1,
            "keepalive": False,
        }


type Load = Workload | OneAtATime

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
# (spec/decisions/0020, spec/decisions/0026).
RATES = (100, 200, 500, 1000, 2000)

# For llama.cpp: a stream of 20 tokens, the same work every time. A seed and a temperature of 0
# fix the model's choices, and Qwen's own switch turns its reasoning off, so the tokens are the
# answer (spec/decisions/0026).
LLAMA_20 = OneAtATime(
    name="llama-20",
    path="/api/chat/stream",
    body={
        "messages": QUESTION,
        "parameters": {
            "max_tokens": 20,
            "temperature": 0,
            "seed": 1,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    },
    requests=30,
    warmup_requests=3,
)
