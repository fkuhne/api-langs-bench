# The backends

Each backend serves [the contract](../contract/README.md) with its in-process fake. This page says how each is set up, with the documentation it follows (R6), and what was measured when it was built. These are a step's checks, not the benchmark's results; those come from the runner (plan step 1.6) onwards.

**The machine for every number here:**
- **Host:** an Apple M3 with 8 cores and 8 GB, on macOS 14.3.
- **Docker:** Docker 29.5.2 and Compose 5.5.1, in Colima's VM: aarch64, 4 CPUs, 5 GiB, Ubuntu 24.04.4.
- **Load:** nothing else was running in Docker.

## Python: FastAPI

[`backends/python-fastapi/`](../backends/python-fastapi/), built in plan step 1.3 ([0014](../spec/decisions/0014-the-python-backend-fresh-from-the-contract-on-uvicorn-standard-and-fastapis-sse.md)).

**How it's set up:**
- **Versions:** FastAPI 0.143.0 on Starlette 1.10.0 and Pydantic 2.14.3, served by uvicorn 0.54.0 with its `standard` extras, on Python 3.14.8.
- **Why `uvicorn[standard]`:** it's what [FastAPI's deployment page](https://fastapi.tiangolo.com/deployment/manually/) recommends. The running server has uvloop 0.23.0's event loop and httptools 0.9.0's parsers loaded (in `/proc/1/maps`).
- **One process,** with uvicorn's defaults, its access log included, until plan step 3.1's rule.
- **The stream** goes through FastAPI's own `EventSourceResponse`.
- **Started with** `docker compose up -d --wait python-fastapi`, on `127.0.0.1:8001`.

**Measured on 2026-11-06:**

| What | Result | How |
|---|---|---|
| Image | 193 MiB unpacked; 56.6 MB compressed | `du -sx /` in the image; `docker image inspect` (`docker image ls` says 263 MB, counting both) |
| Start-up | Ready 0.71 s after `docker compose up -d` began | The host polls `/api/health/ready` every 10 ms |
| Idle memory | 45 MiB, 0.3% CPU | `docker stats --no-stream`, a few seconds after start-up |
| Liveness | 0.6 ms median, 5.0 ms max | 50 requests from a container on Compose's network, each on a new connection |
| Gates | 72 tests, 100% coverage | `docker compose run --rm python-fastapi-checks` |

**The answers match the contract's page, byte for byte.** The example request (`max_tokens: 5`) gets `{"content":"A backend in front of","reasoning":null,…}` whole. Streamed, it gets five `token` events and a `done` event, with `cache-control: no-cache` and `x-accel-buffering: no`. A reserved key gets a 422. `fake_error` with 503 after one token gets one `token` event, then `error` with status 503.

**The pace,** with `FAKE_FIRST_TOKEN_MS=100` and `FAKE_TOKEN_GAP_MS=20`. Ten streams of ten tokens, and ten whole answers:

| Measured from | First token (want 100 ms) | Gap (want 20 ms) | Whole answer (want 280 ms) |
|---|---|---|---|
| The host, through Colima's port forwarding | median 112.5 ms, 108.0 to 117.2 | median 19.7 ms, 6.2 to 31.2 | median 293.1 ms, 291.0 to 300.6 |
| A container on Compose's network | median 109.0 ms, 105.1 to 116.2 | median 19.5 ms, 1.2 to 45.9 | median 293.2 ms, 285.8 to 299.1 |

- **The average pace holds:** the median gap is 20 ms, because each token keeps its own deadline. A late token is followed by a short gap.
- **But each wait wakes late,** by about 10 ms. That's the machine, not the backend: see the next section.

**A client that leaves.** In a test, the client leaves a stream after two tokens, at a 20 ms gap, served by uvicorn over a real socket. The fake's stream is closed, and it made at most three more tokens, in 20 runs out of 20. FastAPI holds up to two events between the fake and the socket ([0014](../spec/decisions/0014-the-python-backend-fresh-from-the-contract-on-uvicorn-standard-and-fastapis-sse.md)). How fast this happens under load is plan step 3.3.

## Timers in Docker's VM on this Mac

In a bare `python:3.14.8-slim-trixie` container, with no backend involved, each sleep of 20 ms, 200 times, wakes this much later than asked:

| Sleep | Median | p90 | p99 | Max |
|---|---|---|---|---|
| `time.sleep(0.02)` | 6.84 ms | 10.54 | 11.20 | 13.93 |
| `asyncio.sleep(0.02)` | 7.15 ms | 10.53 | 10.82 | 10.85 |

The VM's kernel runs tickless (`CONFIG_NO_HZ_FULL=y`), on the `arch_sys_counter` clock source.

### Where the delay comes from

Measured on 2026-11-09, on the same machine. Colima runs its VM on Apple's Virtualization.framework (`vmType: vz`), with 4 virtual CPUs. The probe below sleeps 20 ms 200 times, each way, and prints how much later than asked each sleep woke. The busy loops are shell loops (`while :; do :; done`) started beside it.

| Where | Sleep | Median | p90 | p99 | Max |
|---|---|---|---|---|---|
| A container, the VM idle | `time.sleep` | 4.39 ms | 6.11 | 6.44 | 6.54 |
| | `asyncio.sleep` | 5.31 ms | 6.14 | 12.97 | 15.54 |
| A container, 1 busy loop beside it | `time.sleep` | 5.07 ms | 6.03 | 6.16 | 6.17 |
| | `asyncio.sleep` | 5.25 ms | 5.70 | 6.10 | 6.22 |
| A container, 4 busy loops beside it | `time.sleep` | 0.07 ms | 0.09 | 2.32 | 2.69 |
| | `asyncio.sleep` | 0.08 ms | 0.11 | 3.21 | 5.02 |
| macOS itself, no Docker (Python 3.10.16) | `time.sleep` | 4.24 ms | 5.06 | 15.47 | 15.92 |
| | `asyncio.sleep` | 1.20 ms | 1.33 | 7.45 | 11.22 |
| macOS itself, 1 busy loop beside it | `time.sleep` | 5.00 ms | 5.01 | 5.01 | 5.02 |
| | `asyncio.sleep` | 1.02 ms | 1.04 | 1.07 | 1.08 |

- **The cause is the VM's idle virtual CPUs.** While a virtual CPU has nothing to run, it sleeps on macOS, and macOS wakes it late. With all four kept busy, a sleep wakes within 0.1 ms at the median.
- **The idle VM's delay varies by day:** 6.84 ms at the median on 2026-11-06, 4.39 ms on 2026-11-09.
- **macOS's own sleeps are late too,** by 1 to 5 ms. The flat 5.00 ms looks like timer slack that macOS adds on purpose (unchecked).

<details>
<summary>The probe, and how it was run</summary>

```python
import asyncio, statistics, time

N, GAP = 200, 0.02

def summary(name, late):
    late = sorted(x * 1000 for x in late)
    q = lambda p: late[min(len(late) - 1, int(p * len(late)))]
    print(f"{name:22} median {statistics.median(late):6.2f}  p90 {q(0.90):6.2f}  p99 {q(0.99):6.2f}  max {late[-1]:6.2f} ms")

late = []
for _ in range(N):
    t = time.perf_counter(); time.sleep(GAP); late.append(time.perf_counter() - t - GAP)
summary("time.sleep(0.02)", late)

async def main():
    late = []
    for _ in range(N):
        t = time.perf_counter(); await asyncio.sleep(GAP); late.append(time.perf_counter() - t - GAP)
    summary("asyncio.sleep(0.02)", late)
asyncio.run(main())
```

In a container, with `$spin` busy loops beside it (0, 1 or 4):

```sh
docker run --rm -i python:3.14.8-slim-trixie \
  sh -c "for i in \$(seq 1 $spin); do (while :; do :; done) & done; python -I -" < sleepprobe.py
```

On macOS itself: `python3 -I sleepprobe.py`.

</details>

**What it means for the benchmark** ([0015](../spec/decisions/0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)):
- **On this machine,** a paced fake's own error, about 4 to 11 ms per wait, is larger than what a backend adds to a token. Any language's fake will carry it.
- **The error shrinks as the load grows.** A backend that burns more CPU keeps the virtual CPUs busier, so its fake keeps closer to the pace. Subtracting a measured error can't correct that.
- **The conformance suite's timing check** (plan step 1.5) takes its tolerance from a measurement of the machine's timers.
- **The report's timing numbers come from native Linux.** This Mac is for building, the gates, and the numbers that don't depend on timers.
