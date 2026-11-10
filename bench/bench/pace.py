"""The pace rule, and the probe of the machine's timers its tolerance comes from
(spec/decisions/0017).

An event's lateness is when it arrives, after the request was sent, less its due time. A paced
stream passes when no event is early, its lateness doesn't add up from its first quarter to its
last, and its median lateness is within the tolerance.
"""

import math
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

# What a backend may add over the machine's own timer error, at the median. Fixed from step
# 1.5's runs (spec/decisions/0017).
MARGIN_MS = 10.0

# The probe: this many sleeps, each to a deadline this long after the last one's.
PROBE_SLEEPS = 200
PROBE_GAP_MS = 10


@dataclass(frozen=True)
class Tolerance:
    """How late the machine's timers wake, and the tolerance taken from it."""

    median_ms: float
    p99_ms: float
    margin_ms: float = MARGIN_MS

    @property
    def ms(self) -> float:
        """The tolerance: the probe's p99, plus the margin."""
        return self.p99_ms + self.margin_ms

    @classmethod
    def of(cls, lateness_ms: Sequence[float], margin_ms: float = MARGIN_MS) -> Tolerance:
        """The tolerance from a probe's lateness, one value per sleep."""
        return cls(statistics.median(lateness_ms), percentile(lateness_ms, 99), margin_ms)


def probe(
    sleeps: int = PROBE_SLEEPS,
    gap_ms: float = PROBE_GAP_MS,
    clock: Callable[[], int] = time.perf_counter_ns,
    sleep: Callable[[float], None] = time.sleep,
) -> list[float]:
    """How late each of `sleeps` sleeps wakes, in milliseconds. Each sleeps to a deadline
    `gap_ms` after the last one's, as the fakes wait for each token's time."""
    gap_ns = round(gap_ms * 1_000_000)
    start = clock()
    lateness = []
    for index in range(1, sleeps + 1):
        deadline = start + index * gap_ns
        sleep(max(0, deadline - clock()) / 1e9)
        lateness.append((clock() - deadline) / 1e6)
    return lateness


def percentile(values: Sequence[float], p: float) -> float:
    """The nearest-rank percentile: the smallest value at least p% of them don't exceed."""
    ordered = sorted(values)
    rank = max(1, math.ceil(len(ordered) * p / 100))
    return ordered[rank - 1]


def lateness_ms(sent: int, arrivals: Sequence[int], due_ms: Sequence[float]) -> list[float]:
    """Each event's lateness, in milliseconds: its arrival after `sent`, both in nanoseconds,
    less its due time."""
    return [(at - sent) / 1e6 - due for at, due in zip(arrivals, due_ms, strict=True)]


@dataclass(frozen=True)
class Pace:
    """How late each event of one stream came, or each of several single events."""

    lateness_ms: tuple[float, ...]

    @property
    def median_ms(self) -> float:
        return statistics.median(self.lateness_ms)

    @property
    def drift_ms(self) -> float | None:
        """The median lateness of the last quarter, less the first quarter's; None for fewer than
        four events."""
        quarter = len(self.lateness_ms) // 4
        if quarter == 0:
            return None
        first = statistics.median(self.lateness_ms[:quarter])
        last = statistics.median(self.lateness_ms[-quarter:])
        return last - first

    def problems(self, tolerance: Tolerance, *, drift: bool = True) -> list[str]:
        """What breaks the pace rule; empty if nothing does. `drift` is False for single events
        repeated, whose lateness can't add up."""
        found = []
        early = [(index, late) for index, late in enumerate(self.lateness_ms) if late < 0]
        if early:
            listed = ", ".join(f"#{index} by {-late:.3f} ms" for index, late in early)
            found.append(f"{len(early)} early: {listed}")
        if drift and self.drift_ms is not None and self.drift_ms > tolerance.ms:
            found.append(
                f"lateness adds up: the last quarter's median is {self.drift_ms:.2f} ms later than "
                f"the first quarter's, beyond the tolerance of {tolerance.ms:.2f} ms"
            )
        if self.median_ms > tolerance.ms:
            found.append(
                f"the median lateness is {self.median_ms:.2f} ms, beyond the tolerance of "
                f"{tolerance.ms:.2f} ms"
            )
        return found
