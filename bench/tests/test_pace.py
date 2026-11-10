"""The pace rule and the timer probe (spec/decisions/0017)."""

import pytest

from bench.pace import Pace, Tolerance, lateness_ms, percentile, probe


class Clock:
    """A clock in nanoseconds that each sleep moves on by what it asked, plus `late` ms."""

    def __init__(self, late_ms: list[float]) -> None:
        self.now = 1_000_000_000
        self.late_ms = late_ms
        self.asked: list[float] = []

    def __call__(self) -> int:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.asked.append(seconds)
        self.now += round(seconds * 1e9 + self.late_ms.pop(0) * 1e6)


def test_the_probe_measures_each_sleeps_lateness() -> None:
    clock = Clock([1.0, 0.5, 2.0])

    got = probe(sleeps=3, gap_ms=10, clock=clock, sleep=clock.sleep)

    assert got == pytest.approx([1.0, 0.5, 2.0])
    assert clock.asked == pytest.approx([0.010, 0.009, 0.0095])


def test_the_probe_sleeps_to_deadlines_so_lateness_doesnt_add_up() -> None:
    clock = Clock([15.0, 0.0, 0.0])

    got = probe(sleeps=3, gap_ms=10, clock=clock, sleep=clock.sleep)

    # The second deadline had passed: it doesn't sleep, and is 5 ms late. The third is on time.
    assert got == pytest.approx([15.0, 5.0, 0.0])
    assert clock.asked == pytest.approx([0.010, 0.0, 0.005])


@pytest.mark.parametrize(
    ("p", "want"),
    [(50, 3.0), (99, 5.0), (100, 5.0), (0, 1.0), (20, 1.0), (21, 2.0)],
)
def test_the_nearest_rank_percentile(p: float, want: float) -> None:
    assert percentile([5.0, 1.0, 4.0, 2.0, 3.0], p) == want


def test_the_tolerance_is_the_probes_p99_plus_the_margin() -> None:
    tolerance = Tolerance.of([float(n) for n in range(1, 201)], margin_ms=5.0)

    assert (tolerance.median_ms, tolerance.p99_ms, tolerance.ms) == (100.5, 198.0, 203.0)


def test_lateness_is_the_arrival_after_the_send_less_the_due_time() -> None:
    got = lateness_ms(sent=1_000_000, arrivals=[101_500_000, 122_000_000], due_ms=[100, 120])

    assert got == pytest.approx([0.5, 1.0])


TOLERANCE = Tolerance(median_ms=1.0, p99_ms=2.0, margin_ms=3.0)


def test_a_stream_on_time_passes() -> None:
    pace = Pace(tuple([0.5, 2.0, 1.0, 4.9] * 4))

    assert pace.problems(TOLERANCE) == []


def test_an_early_event_fails_by_any_amount() -> None:
    pace = Pace((1.0, -0.001, 1.0, 1.0))

    (problem,) = pace.problems(TOLERANCE)

    assert problem.startswith("1 early: #1 by 0.001 ms")


def test_lateness_that_adds_up_fails() -> None:
    pace = Pace(tuple(0.5 * index for index in range(16)))

    (problem,) = pace.problems(TOLERANCE)

    assert problem.startswith("lateness adds up")
    assert pace.drift_ms == pytest.approx(6.0)


def test_a_median_beyond_the_tolerance_fails() -> None:
    pace = Pace((6.0, 5.0, 6.0, 5.0))

    (problem,) = pace.problems(TOLERANCE)

    assert problem.startswith("the median lateness is 5.50 ms")


def test_repeated_single_events_skip_the_drift() -> None:
    pace = Pace((0.0, 0.0, 0.0, 0.0, 6.0, 6.0, 6.0, 6.0))

    assert pace.problems(TOLERANCE) != []
    assert pace.problems(TOLERANCE, drift=False) == []


def test_fewer_than_four_events_have_no_drift() -> None:
    assert Pace((1.0, 9.0, 1.0)).drift_ms is None
