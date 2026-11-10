"""Every backend the evaluation tool knows, by its Compose service (compose.yaml)."""

BACKENDS = ("python-fastapi", "go-nethttp", "go-gin")
# The port each listens on, in its own container.
PORT = 8000


def url(service: str, path: str = "") -> str:
    """Where `service` answers `path`, on Compose's network."""
    return f"http://{service}:{PORT}{path}"


# Where a backend's answer comes from: the fake inside it, or the fake server, which it calls
# with its upstream client (contract/README.md#the-upstream).
IN_PROCESS = "fake"
FAKE_SERVER = "fake-server"
UPSTREAMS = (IN_PROCESS, FAKE_SERVER)
# llama.cpp's server, with a real model: checked apart, since it needs a download
# (spec/decisions/0025).
LLAMA_CPP = "llama-cpp"
# The model each one's answers name.
MODELS = {IN_PROCESS: "fake", FAKE_SERVER: "fake-server"}
# How long a backend waits for the fake server in the conformance suite, in seconds: short, so
# a check of the upstream's silence doesn't take long.
SUITE_TIMEOUT_S = 1
# How long a backend waits for llama.cpp in the suite: a real model on a CPU is slow.
LLAMA_TIMEOUT_S = 60


def upstream_settings(upstream: str) -> dict[str, str]:
    """The settings that make a backend answer from `upstream`."""
    if upstream == IN_PROCESS:
        return {"LLM_PROVIDER": "fake"}
    return {
        "LLM_PROVIDER": "openai-compatible",
        "LLM_BASE_URL": f"http://{upstream}:8080/v1",
        "LLM_TIMEOUT_SECONDS": str(LLAMA_TIMEOUT_S if upstream == LLAMA_CPP else SUITE_TIMEOUT_S),
    }
