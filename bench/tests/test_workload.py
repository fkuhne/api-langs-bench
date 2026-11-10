"""The workloads, and where the backends are (spec/decisions/0018)."""

from bench.backends import BACKENDS, url
from bench.contract import Contract
from bench.fake import answer
from bench.workload import STREAM_20

CHAT_REQUEST = "#/components/schemas/ChatRequest"


def test_the_workloads_body_is_a_valid_request() -> None:
    assert Contract().validator(CHAT_REQUEST).is_valid(STREAM_20.body)


def test_each_stream_is_due_to_end_at_240_ms() -> None:
    body = STREAM_20.body

    got = answer(STREAM_20.settings, Contract().tokens, body["messages"], body["parameters"])

    assert (len(got.content), got.due_ms) == (20, 240)


def test_the_connections_are_far_more_than_the_rate_needs() -> None:
    open_at_once = STREAM_20.rate * 240 / 1000

    assert STREAM_20.connections >= 10 * open_at_once


def test_a_run_records_the_whole_workload() -> None:
    assert STREAM_20.described() == {
        "name": "stream-20",
        "method": "POST",
        "path": "/api/chat/stream",
        "body": STREAM_20.body,
        "rate_per_s": 100,
        "duration_s": 30,
        "warmup_s": 5,
        "connections": 256,
        "settings": {
            "LLM_PROVIDER": "fake",
            "FAKE_ANSWER_TOKENS": "256",
            "FAKE_REASONING_TOKENS": "0",
            "FAKE_FIRST_TOKEN_MS": "50",
            "FAKE_TOKEN_GAP_MS": "10",
        },
    }


def test_a_backend_answers_at_its_service_name() -> None:
    assert url("go-gin", "/api/health") == "http://go-gin:8000/api/health"
    assert len(BACKENDS) == len(set(BACKENDS)) == 3
