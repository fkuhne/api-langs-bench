"""The production set-up's rule, as seen from outside each backend (spec/decisions/0027)."""

import time
from datetime import UTC, datetime

from conformance.helpers import HI, Backend, Served, post, stream

# How long a line a backend prints may take to reach Docker's log, in seconds.
LOG_DELAY_S = 0.5


def test_no_line_for_each_request(backend: Backend, defaults: Served) -> None:
    # Lines from the backend's start-up are in the log before this.
    time.sleep(LOG_DELAY_S)
    since = datetime.now(UTC).isoformat()

    defaults.client.get("/api/health")
    defaults.client.get("/api/health/ready")
    post(defaults.client, "/api/chat", {"messages": HI})
    stream(defaults.client, {"messages": HI})
    time.sleep(LOG_DELAY_S)

    assert backend.logs(since) == ""
