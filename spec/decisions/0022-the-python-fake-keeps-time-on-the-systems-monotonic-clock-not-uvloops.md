# 0022. The Python fake keeps time on the system's monotonic clock, not uvloop's

- Status: Accepted
- Date: 2026-11-10

## Context

The contract's fake sends each token at its time, and the conformance suite's pace rule allows no event before it ([contract](../../contract/README.md#the-pace), [0017](0017-the-conformance-suite-pytest-that-drives-compose-and-a-pace-rule-from-the-machines-timers.md)).

On 2026-11-10 the suite failed in CI twice out of two, on commit `484c97c`, which changed no backend: the Python backend sent 3 of 42 paced events early, by 0.10 to 0.18 ms, in both attempts ([conformance](../../docs/conformance.md#pythons-fake-sent-tokens-early-on-2026-11-10)). What was found:
- **The Python fake took its time from the event loop's clock,** `loop.time()`, and waited with one `asyncio.sleep`.
- **uvicorn's `standard` install runs on uvloop** ([0014](0014-the-python-backend-fresh-from-the-contract-on-uvicorn-standard-and-fastapis-sse.md)), **whose clock counts whole milliseconds.** In the backend's image, with uvloop 0.23.0, `loop.time()` read 98.0, then 102.0 ms, where asyncio's own loop read 41.5567, then 45.9356. At a wake it was 0.7 to 2.0 ms behind `time.monotonic()` (our run on the Mac).
- **So the fake's start, and every deadline counted from it, could sit up to 2 ms early.** What hid it: the time a request takes to reach the backend, and a machine's late timers. CI's machines that day were faster: Python's median lateness was 0.68 and 0.82 ms, against 1.14 to 2.58 ms in four earlier runs, whose smallest lateness was already 0.15 ms.
- **An early fake favours Python** in every stream timing, by about 0.5 ms on average (computed).

## Decision

The Python fake reads `time.monotonic()` for its start and its deadlines, and reads it again after each wait: if the event loop woke early, it waits again. No token goes before its time.

- **The rest of a wait is asked as 1 ms at least.** uvloop rounds a wait to whole milliseconds, and a shorter one to none, which would make the last stretch a busy loop.
- **A token may now come up to about 1 ms after its time,** on uvloop: the wait ends at the first of uvloop's milliseconds past the deadline. That is the event loop's real resolution, and the pace rule allows it.
- **The contract says it for every backend:** no token goes early, by the system's monotonic clock.
- **uvloop stays.** It's the documented production install.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| The pace rule allows events up to 1 ms early | No code changes, but Python's timings keep a bias in its favour, and the rule would have to trust a number nobody can check from outside |
| Run uvicorn on asyncio's own loop | Its clock is fine, but it departs from the documented production install, to fix a fake |
| Spin until the exact time | On time to the microsecond, but it burns CPU on every token, which would distort the backend's CPU numbers |

## Consequences

- The Python backend's in-process fake wakes a second time for some tokens. That's event-loop work the Go fakes don't do; it's the price of a millisecond clock.
- Numbers made before this record, with the in-process fake, carry the bias for Python: the first numbers among them ([runner](../../docs/runner.md#the-first-numbers-on-2026-11-10-on-a-core-i7-12850hx)). They're development numbers, and stay as they are.
- A backend in another language whose runtime has a coarse clock meets the same rule.

## Assumptions to verify

- [ ] In CI, Python's fake sends no event early: several attempts in a row. To check with this commit.
- [x] The second wait doesn't cost Python a rate it kept. *2026-11-10, on the Mac, one run each on a busy host: at 500 requests a second it kept the rate before and after, with a p50 of 242.4 ms before and 243.5 ms after (`runs/20261110T104733Z-python-fastapi-500rps.json`, `runs/20261110T145513Z-python-fastapi-500rps.json`).* What it costs in CPU is plan step 3.4's to measure.
- [ ] uvloop's clock lags as measured for the reason its code gives: libuv reads a coarse clock. Unchecked: from memory of libuv's source, not read today.

## Sources

- CI's [run 42830465967](https://github.com/fkuhne/api-langs-bench/actions/runs/42830465967), both attempts, and four earlier runs' pace lines, 2026-11-10.
- Our runs in the Python backend's image on the Mac, 2026-11-10: `loop.time()` under asyncio and under uvloop 0.23.0, and its distance from `time.monotonic()` over 500 wakes.
- The owner's pick, 2026-11-10.
