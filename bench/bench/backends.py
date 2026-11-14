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
# The port an upstream listens on, in its own container: llama.cpp's.
UPSTREAM_PORT = 8080


def upstream_url(upstream: str, path: str = "") -> str:
    """Where `upstream` answers `path`, on Compose's network."""
    return f"http://{upstream}:{UPSTREAM_PORT}{path}"


def upstream_settings(upstream: str) -> dict[str, str]:
    """The settings that make a backend answer from `upstream`."""
    if upstream == IN_PROCESS:
        return {"LLM_PROVIDER": "fake"}
    return {"LLM_PROVIDER": "openai-compatible", "LLM_BASE_URL": upstream_url(upstream, "/v1")}
