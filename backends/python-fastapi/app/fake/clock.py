"""The fake's clock: when a token is due, and waiting for it (contract/README.md#the-pace)."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

# The shortest wait asked of the event loop. uvloop counts a wait in whole milliseconds, and
# rounds a shorter one down to none, which would turn the last stretch into a busy loop.
SHORTEST_WAIT_SECONDS = 0.001


class Clock(Protocol):
    """Monotonic time in seconds, and a wait until a given time."""

    def now(self) -> float: ...

    async def sleep_until(self, deadline: float) -> None: ...


class MonotonicClock:
    """The system's monotonic clock, not the event loop's own.

    uvloop's clock counts whole milliseconds and runs up to 2 ms behind, so a wait measured on
    it can end before its time (spec/decisions/0022).
    """

    def __init__(
        self,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._monotonic = monotonic
        self._sleep = sleep

    def now(self) -> float:
        return self._monotonic()

    async def sleep_until(self, deadline: float) -> None:
        """Wait until `deadline`, never less; at once if it has passed, so delays don't add up.

        The event loop may wake early, so the time is read again after each wait.
        """
        while (delay := deadline - self.now()) > 0:
            await self._sleep(max(delay, SHORTEST_WAIT_SECONDS))
