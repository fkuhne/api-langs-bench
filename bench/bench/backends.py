"""Every backend the evaluation tool knows, by its Compose service (compose.yaml)."""

BACKENDS = ("python-fastapi", "go-nethttp", "go-gin")
# The port each listens on, in its own container.
PORT = 8000


def url(service: str, path: str = "") -> str:
    """Where `service` answers `path`, on Compose's network."""
    return f"http://{service}:{PORT}{path}"
