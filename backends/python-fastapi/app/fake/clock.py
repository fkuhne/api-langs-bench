"""The fake's clock: when a token is due, and waiting for it (contract/README.md#the-pace)."""

import asyncio
from typing import Protocol


class Clock(Protocol):
    """Monotonic time in seconds, and a wait until a given time."""

    def now(self) -> float: ...

    async def sleep_until(self, deadline: float) -> None: ...


class LoopClock:
    """The event loop's own clock, the one `asyncio.sleep` counts on."""

    def now(self) -> float:
        return asyncio.get_running_loop().time()

    async def sleep_until(self, deadline: float) -> None:
        """Wait until `deadline`; at once if it has passed, so delays don't add up."""
        delay = deadline - self.now()
        if delay > 0:
            await asyncio.sleep(delay)
