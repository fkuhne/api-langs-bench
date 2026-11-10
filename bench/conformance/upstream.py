"""Requests to the fake upstream server, timed, as a backend's client sends them
(contract/README.md#the-fake-server, spec/decisions/0023)."""

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx2

from bench.compose import Compose
from bench.fake import FakeSettings

SERVICE = "fake-server"
URL = f"http://{SERVICE}:8080"
PATH = "/v1/chat/completions"
DONE = "[DONE]"


@dataclass(frozen=True)
class Chunk:
    """One event of the stream: its data, parsed, or `DONE`; and when it arrived, in
    nanoseconds on the monotonic clock."""

    data: Any
    at: int


@dataclass(frozen=True)
class Chunked:
    """A stream's response, its chunks, and when the request went and its headers came."""

    response: httpx2.Response
    chunks: list[Chunk]
    sent: int
    headers_at: int

    def deltas(self) -> list[tuple[str, str, int]]:
        """Each token: `content` or `reasoning_content`, its text, and when it arrived."""
        found = []
        for chunk in self.chunks:
            choices = [] if chunk.data == DONE else chunk.data.get("choices", [])
            for key in ("reasoning_content", "content"):
                if choices and isinstance(choices[0]["delta"].get(key), str):
                    found.append((key, choices[0]["delta"][key], chunk.at))
        return found


class Upstream:
    """The fake server's service, restarted only when a check needs other settings."""

    def __init__(self, compose: Compose) -> None:
        self._compose = compose
        self._settings: FakeSettings | None = None
        self.client = httpx2.Client(base_url=URL, timeout=10)

    def serve(self, settings: FakeSettings) -> httpx2.Client:
        """The fake server's client, with the server running with `settings`."""
        if self._settings != settings:
            self._compose.start(SERVICE, settings.environment())
            self._settings = settings
        return self.client

    def logs(self, lines: int = 20) -> str:
        return self._compose.logs(SERVICE, lines)

    def restore(self) -> None:
        """Left running with the settings `.env` gives, as Compose started it."""
        self.client.close()
        self._compose.start(SERVICE, {})


def events(buffer: bytes) -> tuple[list[bytes], bytes]:
    """The whole events in `buffer`, each one `data:` line, and the bytes after them."""
    *whole, rest = buffer.split(b"\n\n")
    for event in whole:
        assert event.startswith(b"data: "), f"not a data line: {event!r}"
        assert b"\n" not in event, f"more than one line: {event!r}"
    return [event.removeprefix(b"data: ") for event in whole], rest


def completions(client: httpx2.Client, body: dict[str, Any], *, chunks: int = 0) -> Chunked:
    """One streamed answer, read strictly, each chunk stamped with when it arrived. With
    `chunks`, the client leaves after that many."""
    read: list[Chunk] = []
    buffer = b""
    sent = time.perf_counter_ns()
    with client.stream("POST", PATH, json={**body, "stream": True}) as response:
        headers_at = time.perf_counter_ns()
        if response.status_code != 200:
            response.read()
            return Chunked(response, read, sent, headers_at)
        for raw in response.iter_raw():
            at = time.perf_counter_ns()
            whole, buffer = events(buffer + raw)
            for data in whole:
                text = data.decode()
                read.append(Chunk(DONE if text == DONE else json.loads(text), at))
            if chunks and len(read) >= chunks:
                return Chunked(response, read, sent, headers_at)
    assert buffer == b"", f"the stream ended inside an event: {buffer!r}"
    return Chunked(response, read, sent, headers_at)
