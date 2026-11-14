"""The workloads, and where the backends are (spec/decisions/0018)."""

from bench.backends import BACKENDS, MODELS, UPSTREAMS, upstream_settings, upstream_url, url
from bench.contract import Contract
from bench.fake import answer
from bench.workload import LLAMA_20, RATES, STREAM_20, upstream_body

CHAT_REQUEST = "#/components/schemas/ChatRequest"


def test_the_workloads_body_is_a_valid_request() -> None:
    assert Contract().validator(CHAT_REQUEST).is_valid(STREAM_20.body)


def test_each_stream_is_due_to_end_at_240_ms() -> None:
    body = STREAM_20.body

    got = answer(STREAM_20.settings, Contract().tokens, body["messages"], body["parameters"])

    assert (len(got.content), got.due_ms) == (20, STREAM_20.due_ms) == (20, 240)


def test_the_connections_are_four_times_the_streams_open_at_once() -> None:
    assert [STREAM_20.at(rate).connections for rate in RATES] == [96, 192, 480, 960, 1920]
    assert STREAM_20.at(3).connections == 3


def test_another_rate_changes_nothing_else() -> None:
    faster = STREAM_20.at(500)

    assert faster.rate == 500
    assert (faster.name, faster.body, faster.settings) == (
        STREAM_20.name,
        STREAM_20.body,
        STREAM_20.settings,
    )


def test_a_run_records_the_whole_workload() -> None:
    assert STREAM_20.described() == {
        "name": "stream-20",
        "method": "POST",
        "path": "/api/chat/stream",
        "body": STREAM_20.body,
        "rate_per_s": 100,
        "duration_s": 30,
        "warmup_s": 5,
        "connections": 96,
        "due_ms": 240,
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


def test_each_upstream_has_its_settings_and_its_models_name() -> None:
    assert upstream_settings("fake") == {"LLM_PROVIDER": "fake"}
    assert upstream_settings("fake-server") == {
        "LLM_PROVIDER": "openai-compatible",
        "LLM_BASE_URL": "http://fake-server:8080/v1",
    }
    assert upstream_settings("llama-cpp")["LLM_BASE_URL"] == "http://llama-cpp:8080/v1"
    assert upstream_url("llama-cpp", "/health") == "http://llama-cpp:8080/health"
    assert [MODELS[upstream] for upstream in UPSTREAMS] == ["fake", "fake-server"]


def test_a_workloads_label_and_settings_are_its_own() -> None:
    assert (STREAM_20.at(500).label, STREAM_20.environment) == (
        "500rps",
        STREAM_20.settings.environment(),
    )
    assert (LLAMA_20.label, LLAMA_20.environment) == ("30x1", {})


def test_the_upstream_alone_gets_what_a_backends_client_sends() -> None:
    alone = STREAM_20.alone()

    assert alone.path == "/v1/chat/completions"
    assert alone.body == {
        "max_tokens": 20,
        "model": "local",
        "messages": STREAM_20.body["messages"],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    assert (alone.rate, alone.settings, alone.name) == (100, STREAM_20.settings, "stream-20")


def test_a_whole_answers_request_asks_for_no_stream() -> None:
    body = {"messages": [{"role": "user", "content": "Hi"}]}

    assert upstream_body(body, stream=False) == {"model": "local", "messages": body["messages"]}


def test_llama_cpp_gets_the_same_work_every_time() -> None:
    parameters = LLAMA_20.body["parameters"]

    assert Contract().validator(CHAT_REQUEST).is_valid(LLAMA_20.body)
    assert (parameters["max_tokens"], parameters["temperature"], parameters["seed"]) == (20, 0, 1)
    assert parameters["chat_template_kwargs"] == {"enable_thinking": False}
    alone = LLAMA_20.alone()
    assert (alone.path, alone.body["stream"], alone.body["seed"]) == (
        "/v1/chat/completions",
        True,
        1,
    )
    assert LLAMA_20.described() == {
        "name": "llama-20",
        "method": "POST",
        "path": "/api/chat/stream",
        "body": LLAMA_20.body,
        "requests": 30,
        "warmup_requests": 3,
        "connections": 1,
        "keepalive": False,
    }
