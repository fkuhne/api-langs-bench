"""Liveness and readiness (contract/README.md#the-endpoints)."""

from conformance.helpers import Check, Served


def test_liveness(defaults: Served, check: Check) -> None:
    response = defaults.client.get("/api/health")

    assert check.json(response, 200, "Liveness") == {"status": "ok"}


def test_readiness(defaults: Served, check: Check) -> None:
    response = defaults.client.get("/api/health/ready")

    assert check.json(response, 200, "Readiness") == {"status": "ok", "checks": {"llm": "ok"}}
