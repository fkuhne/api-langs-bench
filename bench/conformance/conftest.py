"""The conformance suite's fixtures: each backend, started with the settings a check needs
(spec/decisions/0017).

Each check takes one of three fixtures, which names the settings it needs: `defaults`, `paced`,
or `backend` alone, for the checks that start it with invalid ones. The checks run backend by
backend, in that order, so each backend restarts only when its settings change.
"""

from collections.abc import Iterator

import pytest

from bench.compose import Compose
from bench.contract import Contract
from bench.fake import FakeSettings
from bench.pace import PROBE_GAP_MS, PROBE_SLEEPS, Tolerance, probe
from conformance.helpers import Backend, Check, Served

# Every backend the suite checks, by its Compose service. Each listens on port 8000.
BACKENDS = ("python-fastapi", "go-nethttp", "go-gin")

DEFAULTS = FakeSettings()
# The first token at 100 ms, then one every 20 ms: 2 reasoning tokens, then 40 answer tokens.
PACED = FakeSettings(answer_tokens=40, reasoning_tokens=2, first_token_ms=100, token_gap_ms=20)

# What the run measured of the pace, printed at its end.
REPORT = pytest.StashKey[list[str]]()


@pytest.fixture(scope="session")
def contract() -> Contract:
    return Contract()


@pytest.fixture(scope="session")
def check(contract: Contract) -> Check:
    return Check(contract)


@pytest.fixture(scope="session")
def compose() -> Compose:
    return Compose()


@pytest.fixture(scope="session", params=BACKENDS)
def backend(request: pytest.FixtureRequest, compose: Compose) -> Iterator[Backend]:
    backend = Backend(request.param, compose)
    yield backend
    backend.forget()
    # Left running with the settings `.env` gives, as Compose started it.
    compose.start(backend.service, {})


@pytest.fixture
def defaults(backend: Backend) -> Served:
    """The backend with the contract's default settings."""
    return backend.serve(DEFAULTS)


@pytest.fixture
def paced(backend: Backend) -> Served:
    """The backend with a paced fake that reasons first."""
    return backend.serve(PACED)


@pytest.fixture(scope="session", autouse=True)
def tolerance(pytestconfig: pytest.Config) -> Tolerance:
    """The machine's timer error, measured before any check, and the pace's tolerance."""
    tolerance = Tolerance.of(probe())
    pytestconfig.stash[REPORT].append(
        f"the machine's timers: {PROBE_SLEEPS} sleeps of {PROBE_GAP_MS} ms woke "
        f"{tolerance.median_ms:.2f} ms late at the median, {tolerance.p99_ms:.2f} ms at the p99; "
        f"tolerance {tolerance.ms:.2f} ms (the p99 plus {tolerance.margin_ms:.0f} ms)"
    )
    return tolerance


@pytest.fixture
def report(pytestconfig: pytest.Config) -> list[str]:
    """Lines printed at the end of the run."""
    return pytestconfig.stash[REPORT]


def pytest_configure(config: pytest.Config) -> None:
    config.stash[REPORT] = []


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Backend by backend; for each, the checks at the defaults, then paced, then the rest."""

    def order(item: pytest.Item) -> tuple[int, int]:
        callspec = getattr(item, "callspec", None)
        service = callspec.params.get("backend") if callspec else None
        names = getattr(item, "fixturenames", ())
        settings = 0 if "defaults" in names else 1 if "paced" in names else 2
        return (BACKENDS.index(service) if service in BACKENDS else -1, settings)

    items.sort(key=order)


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    lines = config.stash.get(REPORT, [])
    if lines:
        terminalreporter.section("the pace")
        for line in lines:
            terminalreporter.write_line(line)
