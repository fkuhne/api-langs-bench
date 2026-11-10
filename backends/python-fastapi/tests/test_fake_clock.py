"""The fake's clock never ends a wait before its time (spec/decisions/0022)."""

import pytest

from app.fake.clock import SHORTEST_WAIT_SECONDS, MonotonicClock

pytestmark = pytest.mark.anyio


class EarlyLoop:
    """An event loop whose waits each end `early` seconds before their time, as uvloop's can."""

    def __init__(self, early: float = 0.0) -> None:
        self.time = 100.0
        self.early = early
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.time

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.time += max(delay - self.early, 0.0)

    def clock(self) -> MonotonicClock:
        return MonotonicClock(self.monotonic, self.sleep)


async def test_a_wait_ends_at_its_time() -> None:
    loop = EarlyLoop()

    await loop.clock().sleep_until(100.02)

    assert loop.sleeps == pytest.approx([0.02])
    assert loop.time == pytest.approx(100.02)


async def test_a_time_that_has_passed_isnt_waited_for() -> None:
    loop = EarlyLoop()

    await loop.clock().sleep_until(99.0)
    await loop.clock().sleep_until(100.0)

    assert loop.sleeps == []


async def test_a_wait_that_ends_early_goes_on_to_its_time() -> None:
    loop = EarlyLoop(early=0.0004)

    await loop.clock().sleep_until(100.02)

    # The loop woke 0.4 ms early. The rest is asked as a whole millisecond, never as nothing.
    assert loop.sleeps == pytest.approx([0.02, SHORTEST_WAIT_SECONDS])
    assert loop.time >= 100.02


async def test_by_default_it_waits_on_the_systems_clock() -> None:
    clock = MonotonicClock()
    start = clock.now()

    await clock.sleep_until(start + 0.005)

    assert clock.now() >= start + 0.005
