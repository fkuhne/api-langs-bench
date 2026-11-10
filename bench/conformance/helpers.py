"""Requests to a backend, timed, and the checks every answer goes through (contract/README.md)."""

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx2

from bench.backends import FAKE_SERVER, IN_PROCESS, MODELS, upstream_settings, url
from bench.compose import Compose
from bench.contract import Contract
from bench.fake import Answer, FakeSettings, answer
from bench.sse import Event, EventParser, check_order

HI = [{"role": "user", "content": "Hi"}]
# One event of the stream, as `POST /api/chat/stream` describes it.
STREAM_EVENT = (
    "#/paths/~1api~1chat~1stream/post/responses/200/content/text~1event-stream/itemSchema"
)
# Each event's data, by the event's name.
EVENT_DATA = {
    "reasoning": "ReasoningDelta",
    "token": "ContentDelta",
    "done": "StreamEnd",
    "error": "ErrorEvent",
}
SCHEMAS = (
    "Completion",
    "Error",
    "Liveness",
    "Readiness",
    "ValidationError",
    *EVENT_DATA.values(),
)

type Body = str | dict[str, Any]


@dataclass(frozen=True)
class Served:
    """A backend's client, the settings its fake runs with, and the model its answers name."""

    client: httpx2.Client
    settings: FakeSettings
    model: str

    def expect(self, body: Body, tokens: tuple[str, ...]) -> Answer:
        """What the contract says this backend answers `body`."""
        request = json.loads(body) if isinstance(body, str) else body
        return answer(
            self.settings, tokens, request["messages"], request.get("parameters", {}), self.model
        )


@dataclass(frozen=True)
class Streamed:
    """A stream's response, its events, and when the request went and its headers came, in
    nanoseconds on the monotonic clock."""

    response: httpx2.Response
    events: list[Event]
    sent: int
    headers_at: int


class Backend:
    """One backend's service, answering from one upstream: the fake inside it, or the fake
    server. It's restarted only when a check needs other settings."""

    def __init__(self, service: str, compose: Compose, upstream: str = IN_PROCESS) -> None:
        self.service = service
        self.upstream = upstream
        self._compose = compose
        self._serving: Served | None = None

    @property
    def name(self) -> str:
        """The backend and its upstream, for a report's line."""
        if self.upstream == IN_PROCESS:
            return self.service
        return f"{self.service} via {self.upstream}"

    def environment(self, settings: FakeSettings) -> dict[str, str]:
        """The backend's settings: the fake's, and its upstream's."""
        return settings.environment() | upstream_settings(self.upstream)

    def serve(self, settings: FakeSettings) -> Served:
        """The backend, running with `settings`. Behind the fake server, that runs with them
        too."""
        if self._serving is None or self._serving.settings != settings:
            self.forget()
            if self.upstream == FAKE_SERVER:
                self._compose.start(FAKE_SERVER, settings.environment())
            self._compose.start(self.service, self.environment(settings))
            client = httpx2.Client(base_url=url(self.service), timeout=10)
            self._serving = Served(client, settings, MODELS[self.upstream])
        return self._serving

    def forget(self) -> None:
        """Its settings are about to change outside `serve`."""
        if self._serving is not None:
            self._serving.client.close()
            self._serving = None


def _content(body: Body) -> str:
    return body if isinstance(body, str) else json.dumps(body)


def post(client: httpx2.Client, path: str, body: Body) -> httpx2.Response:
    """One chat request, its body sent as JSON."""
    return client.post(path, content=_content(body), headers={"Content-Type": "application/json"})


def stream(client: httpx2.Client, body: Body) -> Streamed:
    """One streamed answer, read strictly, each event stamped with when it arrived."""
    parser = EventParser()
    events: list[Event] = []
    sent = time.perf_counter_ns()
    with client.stream(
        "POST",
        "/api/chat/stream",
        content=_content(body),
        headers={"Content-Type": "application/json"},
    ) as response:
        headers_at = time.perf_counter_ns()
        if response.status_code != 200:
            response.read()
            return Streamed(response, events, sent, headers_at)
        for chunk in response.iter_raw():
            events += parser.feed(chunk, time.perf_counter_ns())
        parser.close()
    return Streamed(response, events, sent, headers_at)


def normalized(value: Any) -> Any:
    """JSON as the contract compares it: a field that is null may be left out."""
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


def expected_events(expected: Answer) -> list[tuple[str, Any]]:
    """The events the contract says the stream holds, as `Check.events` gives them."""
    return [(name, normalized(data)) for name, data in expected.events()]


def media_type(response: httpx2.Response) -> str:
    """The response's media type, without its parameters, such as a charset."""
    return response.headers.get("content-type", "").split(";")[0].strip()


class Check:
    """The contract's checks, with its schemas' validators built once."""

    def __init__(self, contract: Contract) -> None:
        self.tokens = contract.tokens
        self._schemas = {
            name: contract.validator(f"#/components/schemas/{name}") for name in SCHEMAS
        }
        self._event = contract.validator(STREAM_EVENT)

    def valid(self, schema: str, value: Any) -> None:
        """`value` is valid against the contract's schema of that name."""
        errors = [error.message for error in self._schemas[schema].iter_errors(value)]
        assert not errors, f"not a valid {schema}: {errors} in {value!r}"

    def json(self, response: httpx2.Response, status: int, schema: str) -> Any:
        """The response has this status, and a JSON body valid against `schema`."""
        assert response.status_code == status, (response.status_code, response.text)
        assert media_type(response) == "application/json", response.headers
        body = response.json()
        self.valid(schema, body)
        return body

    def events(self, streamed: Streamed) -> list[tuple[str, Any]]:
        """A stream as the contract writes it: its status and headers, every event valid, and
        their order. The events, by name and data, an error's `detail` taken off."""
        response = streamed.response
        assert response.status_code == 200, (response.status_code, response.text)
        assert media_type(response) == "text/event-stream", response.headers
        assert response.headers.get("cache-control") == "no-cache", response.headers
        check_order([event.name for event in streamed.events])
        got = []
        for event in streamed.events:
            errors = [
                e.message
                for e in self._event.iter_errors({"event": event.name, "data": event.data})
            ]
            assert not errors, f"not a valid event: {errors} in {event!r}"
            data = event.value()
            self.valid(EVENT_DATA[event.name], data)
            if event.name == "error":
                data = {key: item for key, item in data.items() if key != "detail"}
            got.append((event.name, normalized(data)))
        return got

    def answers(self, served: Served, body: Body) -> Streamed:
        """Both chat endpoints answer `body` as the contract says: whole, then streamed. The
        stream, for any further checks."""
        expected = served.expect(body, self.tokens)
        response = post(served.client, "/api/chat", body)
        if expected.failure is None:
            got = self.json(response, 200, "Completion")
            assert normalized(got) == normalized(expected.completion())
        else:
            self.json(response, expected.failure, "Error")
        streamed = stream(served.client, body)
        assert self.events(streamed) == expected_events(expected)
        return streamed
