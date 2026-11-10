"""The stream's wire format, read strictly, as the contract gives it
(contract/README.md#the-stream).

Each event is an `event:` line, one `data:` line holding JSON, and a blank line. Lines end with
a line feed alone. One space after a field's colon is optional, as the SSE standard allows.
Comments, lines that start with a colon, may come anywhere. Nothing else is allowed: no `id:`, no
`retry:`, no other field, no field twice.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# The order the contract gives: any reasoning, then any tokens, then one of these, last.
_PIECES = ("reasoning", "token")
_ENDS = ("done", "error")


class ContractError(ValueError):
    """The stream broke the contract: its wire format, or its events' order."""


@dataclass(frozen=True)
class Event:
    """One event, and when its blank line arrived, in nanoseconds on the monotonic clock."""

    name: str
    data: str
    at: int

    def value(self) -> Any:
        """The data, parsed."""
        return json.loads(self.data)


class EventParser:
    """Reads a stream's bytes as they arrive, and returns the events each chunk completes.

    Feed it every chunk with the time it arrived, then close it once the stream has ended.
    """

    def __init__(self) -> None:
        self._buffer = b""
        self._fields: dict[str, str] = {}

    def feed(self, chunk: bytes, at: int) -> list[Event]:
        """The events this chunk completes, each stamped with the chunk's arrival."""
        self._buffer += chunk
        events = []
        while (end := self._buffer.find(b"\n")) >= 0:
            line, self._buffer = self._buffer[:end], self._buffer[end + 1 :]
            event = self._line(line, at)
            if event is not None:
                events.append(event)
        return events

    def close(self) -> None:
        """The stream has ended. It must end on an event's blank line."""
        if self._buffer or self._fields:
            raise ContractError("the stream ended inside an event")

    def _line(self, raw: bytes, at: int) -> Event | None:
        if b"\r" in raw:
            raise ContractError(f"a line holds a carriage return, not a line feed alone: {raw!r}")
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContractError(f"a line isn't UTF-8: {raw!r}") from error
        if line.startswith(":"):
            return None
        if not line:
            return self._dispatch(at)
        field, colon, value = line.partition(":")
        if not colon:
            raise ContractError(f"a line has no colon: {line!r}")
        value = value.removeprefix(" ")
        if field not in ("event", "data"):
            raise ContractError(f"a field the contract doesn't send: {line!r}")
        if field in self._fields:
            raise ContractError(f"an event has two {field} lines")
        if field == "data" and "event" not in self._fields:
            raise ContractError(f"a data line comes before its event line: {line!r}")
        self._fields[field] = value
        return None

    def _dispatch(self, at: int) -> Event | None:
        fields, self._fields = self._fields, {}
        if not fields:
            # A blank line with nothing before it, such as one ending a comment, sends nothing.
            return None
        if "data" not in fields:
            raise ContractError(f"an event has no data line: {fields!r}")
        try:
            json.loads(fields["data"])
        except json.JSONDecodeError as error:
            raise ContractError(f"an event's data isn't JSON: {fields['data']!r}") from error
        return Event(name=fields["event"], data=fields["data"], at=at)


def parse(body: bytes, at: int = 0) -> list[Event]:
    """Every event of a whole stream's body."""
    parser = EventParser()
    events = parser.feed(body, at)
    parser.close()
    return events


def check_order(names: Sequence[str]) -> None:
    """Any `reasoning` events, then any `token` events, then exactly one `done` or `error`, last."""
    if not names or names[-1] not in _ENDS:
        raise ContractError(f"the stream doesn't end with done or error: {list(names)!r}")
    pieces = names[:-1]
    for name in pieces:
        if name not in _PIECES:
            raise ContractError(f"an event out of place: {name!r} in {list(names)!r}")
    ranks = [_PIECES.index(name) for name in pieces]
    if ranks != sorted(ranks):
        raise ContractError(f"a reasoning event comes after a token: {list(names)!r}")
