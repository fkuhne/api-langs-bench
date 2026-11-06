"""Test doubles and parsers shared by the tests."""

import json
from typing import Any


class FakeClock:
    """A clock the tests drive: waiting moves it on at once, and each wait is recorded."""

    def __init__(self) -> None:
        self.time = 0.0
        self.waits: list[float] = []

    def now(self) -> float:
        return self.time

    async def sleep_until(self, deadline: float) -> None:
        self.waits.append(deadline)
        self.time = max(self.time, deadline)


def events(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse a server-sent-events body into (event, data) pairs, skipping comments."""
    parsed = []
    for block in body.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if not line.startswith(":")]
        fields = dict(line.split(": ", 1) for line in lines)
        parsed.append((fields["event"], json.loads(fields["data"])))
    return parsed
