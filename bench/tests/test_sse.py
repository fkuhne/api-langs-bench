"""The strict reading of the stream's wire format (contract/README.md#the-stream)."""

import pytest

from bench.contract import Contract
from bench.sse import ContractError, EventParser, check_order, parse

TOKEN = b'event: token\ndata: {"text":"A"}\n\n'


def test_the_contracts_example_reads_as_its_six_events() -> None:
    events = parse(Contract().examples.stream)

    assert [event.name for event in events] == ["token"] * 5 + ["done"]
    assert events[0].value() == {"text": "A"}
    assert events[-1].value()["finish_reason"] == "length"


def test_the_space_after_a_colon_is_optional() -> None:
    (event,) = parse(b'event:token\ndata:{"text":" A"}\n\n')

    assert (event.name, event.value()) == ("token", {"text": " A"})


def test_only_one_space_is_taken_off() -> None:
    (event,) = parse(b'event: token\ndata:  {"text":"A"}\n\n')

    assert event.data == ' {"text":"A"}'


def test_comments_may_come_anywhere() -> None:
    body = b': ping\n\nevent: token\n: inside\ndata: {"text":"A"}\n: after\n\n: last\n\n'

    assert [event.name for event in parse(body)] == ["token"]


def test_an_event_arrives_with_its_blank_line() -> None:
    parser = EventParser()

    assert parser.feed(b'event: token\ndata: {"te', at=1) == []
    assert parser.feed(b'xt":"A"}\n', at=2) == []
    (event,) = parser.feed(b"\nevent: done\n", at=3)
    parser.feed(b'data: {"model":"fake"}\n\n', at=4)
    parser.close()

    assert (event.name, event.at) == ("token", 3)


def test_events_in_one_chunk_share_its_time() -> None:
    events = EventParser().feed(TOKEN + TOKEN, at=7)

    assert [event.at for event in events] == [7, 7]


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        pytest.param(b'event: token\r\ndata: {"text":"A"}\r\n\r\n', "carriage return", id="CRLF"),
        pytest.param(b'event token\ndata: {"text":"A"}\n\n', "no colon", id="no colon"),
        pytest.param(b'event: token\nid: 1\ndata: {"text":"A"}\n\n', "doesn't send", id="an id"),
        pytest.param(b"retry: 10\nevent: token\ndata: {}\n\n", "doesn't send", id="a retry"),
        pytest.param(b"event: token\nfoo: 1\ndata: {}\n\n", "doesn't send", id="another field"),
        pytest.param(b"event: token\ndata: {}\ndata: {}\n\n", "two data", id="two data lines"),
        pytest.param(b"event: token\nevent: done\ndata: {}\n\n", "two event", id="two events"),
        pytest.param(b'data: {"text":"A"}\nevent: token\n\n', "before its event", id="data first"),
        pytest.param(b"event: token\n\n", "no data", id="no data line"),
        pytest.param(b"event: token\ndata: A\n\n", "isn't JSON", id="data not JSON"),
        pytest.param(b'event: token\ndata: {"text":"\xff"}\n\n', "isn't UTF-8", id="not UTF-8"),
        pytest.param(b'event: token\ndata: {"text":"A"}\n', "inside an event", id="no blank line"),
        pytest.param(b'event: token\ndata: {"text":"A"}', "inside an event", id="a line cut short"),
    ],
)
def test_anything_else_breaks_the_wire_format(body: bytes, reason: str) -> None:
    with pytest.raises(ContractError, match=reason):
        parse(body)


@pytest.mark.parametrize(
    "names",
    [
        ["done"],
        ["error"],
        ["token", "token", "done"],
        ["reasoning", "token", "done"],
        ["reasoning", "reasoning", "error"],
    ],
)
def test_the_order_the_contract_gives(names: list[str]) -> None:
    check_order(names)


@pytest.mark.parametrize(
    "names",
    [
        pytest.param([], id="nothing"),
        pytest.param(["token"], id="no end"),
        pytest.param(["done", "token"], id="a token after the end"),
        pytest.param(["token", "done", "done"], id="two ends"),
        pytest.param(["token", "reasoning", "done"], id="reasoning after a token"),
        pytest.param(["ping", "done"], id="an unknown event"),
    ],
)
def test_any_other_order_breaks_the_contract(names: list[str]) -> None:
    with pytest.raises(ContractError):
        check_order(names)
