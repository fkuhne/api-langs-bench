# The runner

One command sends a workload to each backend in turn, and saves each run once in [`runs/`](../runs/README.md):

```text
docker compose run --rm runner
```

By default it runs every backend at four rates, three times over: 36 runs, in about 25 minutes (computed). Options may follow the command:
- `--backend go-gin` runs one backend; it may be given more than once;
- `--rate 100` runs one rate, in requests a second; it may be given more than once;
- `--passes 1` runs everything once.

Why it's built this way is in [0018](../spec/decisions/0018-the-first-runner-oha-as-the-load-generator-one-streamed-workload-and-runs-committed-as-json.md) and [0020](../spec/decisions/0020-the-first-numbers-a-ladder-of-rates-under-provisional-limits-three-passes.md). This is the first runner, of plan steps 1.6 and 1.8: one workload, with latency and errors. The limits and the rates are provisional, and the other workloads and the resources arrive in Phase 3.

To make the first numbers on a machine, see [The first numbers](#the-first-numbers).

## What a run is

A run is one workload sent to one backend at one rate, once. For each run, the runner ([`runner.py`](../bench/bench/runner.py)):
1. stops the other backends;
2. starts this one in a new container, with the workload's settings, and waits until it's ready;
3. measures how late the machine's timers wake, with the conformance suite's probe ([0015](../spec/decisions/0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md));
4. sends the workload for 5 s, as a warm-up that isn't counted;
5. sends it for 30 s, and keeps what the load generator measured;
6. reads the backend's limits back from Docker, and writes the run's file.

**The passes.** A pass runs every backend at every rate, lowest first. The backends' order rotates from one pass to the next, so no backend always runs first. At the end, the runner prints a Markdown table of its runs: each number's median over the passes, and its range.

**The limits,** provisional until plan step 3.1: every backend's container gets 1 CPU and 512 MiB, from `BACKEND_CPUS` and `BACKEND_MEMORY` in `.env`. Under a 1-CPU limit, Go 1.27.3 sets `GOMAXPROCS` to 2, its minimum, against 4 without one (our run, 2026-11-10). The load generator has no limit, and shares the machine's other CPUs.

At the end, every backend is left running with the settings `.env` gives. Like the conformance suite, the runner starts the backends through Docker's socket, which gives its container root on Docker's host.

**The workload,** `stream-20` ([`workload.py`](../bench/bench/workload.py)):
- `POST /api/chat/stream`, asking for 20 tokens;
- the fake paced: the first token at 50 ms, then one every 10 ms. Each stream is due to end at 240 ms, so about 24 are open at once;
- 100, 500, 1,000 and 2,000 requests a second, provisional until plan step 3.2;
- connections sized to the rate: four times the streams open at once, so 96 at 100 a second and 1,920 at 2,000. Why is [below](#what-the-ladder-rests-on).

**The load generator** is [oha](https://github.com/hatoo/oha) 1.16.0, run inside the runner's container, on Compose's network ([`oha.py`](../bench/bench/oha.py)):
- **Open-loop:** `-q 100` sets the arrival rate, whatever the backend does. `--latency-correction` counts each request's latency from when it was due to be sent, not from when it went.
- **`-w`** waits for the requests still open after 30 s.
- **`-t 30s`** counts a request with no answer after 30 s as an error.
- **Open files:** the runner's container may open 65,536, one for each connection.

## A run's file

`runs/<the start, in UTC>-<the backend>-<the rate>rps.json`, written once and never edited. It holds:

| Field | What |
|---|---|
| `schema` | 2. The first three runs, of plan step 1.6, are 1: no limits, no pass, and no rate in their names |
| `pass` | Which pass the run belongs to |
| `backend` | The Compose service, its image's ID, and its limits as Docker holds it to them: CPUs and bytes of memory, 0 for none |
| `upstream` | `fake`, the in-process fake |
| `workload` | The request, the rate, the durations, the connections, and the fake's settings |
| `load_generator` | oha's version, and its whole command |
| `repository` | The commit, and `dirty`: whether a tracked file differed from it |
| `machine` | Your description of the host, from `BENCH_MACHINE` in `.env`; Docker's version, OS, kernel, architecture, CPUs and memory; Compose's version; and the timer probe's median and p99 |
| `results` | The requests sent and due, the rate reached, whether the rate was kept (99% of the requests due were sent), the counts by status and by error, the latency's p50, p95 and p99, and the time to the first byte |
| `oha` | oha's whole output |

**What the file doesn't hold yet:** the backend's memory and CPU use, and each event's time. The limits are provisional until plan step 3.1, and timing numbers from a Mac never reach the report ([0015](../spec/decisions/0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)).

## The load generator, measured alone

Measured on 2026-11-09, before the runner was written (R4).

**The machine:**
- **Host:** an Apple M3 with 8 cores and 8 GB, on macOS 14.3.
- **Docker:** Docker 29.5.2 and Compose 5.5.1, in Colima's VM: aarch64, 4 CPUs, 5 GiB, Ubuntu 24.04.4.
- **Load:** only `go-nethttp` was running in Docker. oha ran from its own image, `ghcr.io/hatoo/oha:1.16.0`, on Compose's network, and shared the VM's 4 CPUs with the backend.

**Its ceiling.** Without a rate, against `go-nethttp`'s `/api/health`, over 50 connections for 5 s: 163,411 requests a second, all answered. That's 1,600 times the workload's rate. It's the pair's ceiling, not oha's alone, since the backend was answering.

```text
docker run --rm --network api-langs-bench_default ghcr.io/hatoo/oha:1.16.0 --no-tui -z 5s -c 50 http://go-nethttp:8000/api/health
```

**Its latency, against a time we know.** With the workload's settings, each stream is due to end at 240 ms. At 100 a second for 20 s, over 256 connections:

| | p50 | p95 | p99 | Max |
|---|---|---|---|---|
| oha's latency | 241.3 ms | 243.3 ms | 253.7 ms | 267.9 ms |

That's 1.3 ms late at the median. The conformance suite's own client, in Python, saw `net/http`'s streams 4.1 to 5.0 ms late at the median, one stream at a time ([conformance](conformance.md#measured-on-2026-11-09)). The two agree within this Mac's timer error, and the difference has a known cause: under load the VM's CPUs stay busy, and its timers wake closer to their time ([backends](backends.md#where-the-delay-comes-from)).

**Its percentiles match its own per-request times.** The same run, with `--db-url`, wrote each of the 2,000 requests to SQLite. Nearest-rank percentiles of those times, computed by us:

| | p50 | p95 | p99 |
|---|---|---|---|
| oha's JSON | 241.343 ms | 243.347 ms | 253.711 ms |
| From its per-request times | 241.343 ms | 243.330 ms | 253.653 ms |

Each request's time is its end less its due time, in every row.

**Its correction counts a request's wait.** With 10 connections on purpose, the backend can take about 41 streams a second, not 100. For 10 s:

| | Sent | p50 | p99 |
|---|---|---|---|
| `--latency-correction` | 420 of 1,000 due | 3,207.7 ms | 6,042.8 ms |
| Without it | 419 | 241.3 ms | 252.4 ms |

- Without the correction, oha reports what a closed-loop tool reports: every stream took 241 ms, and nothing looks wrong.
- With it, the queue shows.
- **But the requests still due when the time ends are never sent:** 580 of 1,000 here. So a run also records the requests due, and whether the rate was kept. A run whose rate wasn't kept has percentiles that leave out its worst requests.

**How evenly it sends.** From the same per-request times, at 100 a second:
- the gap between one request's due time and the next was 9.98 ms at the median, but from 0.001 to 27.5 ms;
- each request went 0.03 ms after its due time at the median, and 0.83 ms at most.

So oha's due times aren't a fixed grid. When its own timer wakes late, the next requests are due late too, then close together. On this Mac that's the VM's timers again. Whether it's tighter on native Linux is checked on the report's machine.

**The first byte is the first token.** In the runs below, oha's time to the first byte was 51.3 to 53.9 ms at the median, with the first token due at 50 ms. The headers alone come within about 2 ms ([conformance](conformance.md#measured-on-2026-11-09)). So oha's first byte seems to be the body's first byte, which here is the first token. That's from the numbers, unchecked in oha's code; plan step 2.4 needs it checked.

## The first runs, on 2026-11-09

One command, `docker compose run --rm runner`, with `BENCH_MACHINE` set. It took 128 s for the three backends. The machine is the one above; the host was busier than usual, with a load average near 3, and the timer probe shows it.

| Run | Sent | Statuses | p50 | p95 | p99 | Timers, median / p99 |
|---|---|---|---|---|---|---|
| [`20261110T022226Z-python-fastapi`](../runs/20261110T022226Z-python-fastapi.json) | 3,000 at 100.0/s | 200: 3,000 | 244.7 ms | 250.5 ms | 264.1 ms | 2.99 / 13.16 ms late |
| [`20261110T022306Z-go-nethttp`](../runs/20261110T022306Z-go-nethttp.json) | 3,000 at 100.0/s | 200: 3,000 | 241.5 ms | 243.2 ms | 248.0 ms | 2.88 / 11.06 ms late |
| [`20261110T022346Z-go-gin`](../runs/20261110T022346Z-go-gin.json) | 3,000 at 100.0/s | 200: 3,000 | 241.6 ms | 243.5 ms | 249.8 ms | 2.93 / 9.13 ms late |

- Every run kept its rate, with no error. Each is from commit `50c21fd`, with no tracked file changed.
- **These show the runner works. They aren't the first numbers,** which are plan step 1.8's: one run each, on a Mac, with no limits set, over 256 connections. Their files have `schema` 1.

**Disk:** each run's file is 5.2 to 5.3 kB. The runner's image is 138.4 MB compressed, against 128.6 MB for the conformance image. Docker's images take 29.52 GB in all, 0.5 GB more than before this step.

## What the ladder rests on

A quick ladder of rates on 2026-11-09 and 2026-11-10, on the same Mac, to see what plan step 1.8's choices rest on ([0020](../spec/decisions/0020-the-first-numbers-a-ladder-of-rates-under-provisional-limits-three-passes.md)). Each point is 10 s of the `stream-20` request, sent by oha from the runner's image over 2,048 connections, with the backend's CPU read once from `docker stats`. Nothing was saved as a run, so these are a sketch, not results.

| Backend | Rate | p50 | Backend's CPU |
|---|---|---|---|
| Python, FastAPI | 100/s | 245.0 ms | 53% of one CPU |
| Python, FastAPI | 1,500/s | 392.4 ms | 108% |
| Go, `net/http` | 100/s | 242.1 ms | 31% |
| Go, `net/http` | 4,000/s | 241.2 ms | 144% |
| Go, `net/http` | 8,000/s | 245.0 ms | 159% |
| Go, `net/http`, limited to 1 CPU | 4,000/s | 242.9 ms | 97% |

- **At 100 a second nothing separates the backends,** and a 1-CPU limit changes nothing. Higher rates do separate them.
- **Without a limit the comparison isn't equal:** Go took 1.6 CPUs, and Python's one process can't take more than one.

**Two traps in the load generator's set-up** looked like a backend's errors:

| Trap | What happened | What removed it |
|---|---|---|
| Open files | The container's limit is 1,024. With 2,048 connections, oha failed 1,033 requests with "Too many open files", at every rate from 500 a second, against every backend | `--ulimit nofile=65536`: no error at 500 to 8,000 a second against `net/http` |
| Idle connections | uvicorn closes a connection idle for 5 s, its default (`timeout_keep_alive`). With 2,048 connections at 250 a second, most sit idle: oha lost 717 of 3,750 requests, as "connection closed before message completed" and "connection error" | 128 connections, or keep-alive off: 3,750 answers of 200, no error. Go's server sets no idle timeout, so only Python showed it |

So the runner raises its open-files limit, and sizes its connections to the rate: every one is reused within about a second. Whether a server's idle timeout should be measured on purpose is plan step 3.1's question.

## A check of the ladder, on 2026-11-10

One pass, `docker compose run --rm runner --passes 1`, with `BENCH_MACHINE` set: 12 runs in 493 s. The machine is the Mac named above, with a load average near 3 from outside Docker; the timer probe read 1.9 to 2.9 ms late at the median. Every run records its backend's limits as 1 CPU and 536,870,912 bytes.

The table the runner printed:

| Backend | Rate | Runs | p50, ms | p99, ms | Requests | Not 200 | Kept the rate |
|---|---|---|---|---|---|---|---|
| `python-fastapi` | 100/s | 1 | 244.5 | 274.0 | 3000 | 0 | 1 of 1 |
| `python-fastapi` | 500/s | 1 | 242.4 | 550.6 | 15000 | 0 | 1 of 1 |
| `python-fastapi` | 1000/s | 1 | 5439.0 | 10148.6 | 20849 | 0 | 0 of 1 |
| `python-fastapi` | 2000/s | 1 | 479.4 | 3266.3 | 59999 | 36454 | 1 of 1 |
| `go-nethttp` | 100/s | 1 | 241.2 | 255.8 | 3000 | 0 | 1 of 1 |
| `go-nethttp` | 500/s | 1 | 241.2 | 259.7 | 15000 | 0 | 1 of 1 |
| `go-nethttp` | 1000/s | 1 | 241.4 | 292.8 | 30000 | 0 | 1 of 1 |
| `go-nethttp` | 2000/s | 1 | 242.2 | 388.5 | 59998 | 0 | 1 of 1 |
| `go-gin` | 100/s | 1 | 241.5 | 249.6 | 3000 | 0 | 1 of 1 |
| `go-gin` | 500/s | 1 | 241.2 | 256.2 | 15000 | 0 | 1 of 1 |
| `go-gin` | 1000/s | 1 | 241.6 | 279.6 | 30000 | 0 | 1 of 1 |
| `go-gin` | 2000/s | 1 | 242.1 | 349.0 | 59999 | 0 | 1 of 1 |

The runs are `runs/20261110T104652Z-python-fastapi-100rps.json` to `runs/20261110T105415Z-go-gin-2000rps.json`.

- **This checks the runner, and isn't the first numbers:** one pass, on a busy Mac. Each file says `"dirty": true`, because the runner's own code wasn't committed yet when they were made; it's the code of the commit that added them.
- **The load generator's traps are gone:** no "Too many open files", and no error at any rate a backend kept.
- **Python under 1 CPU ran out between 500 and 1,000 a second.** At 1,000 it answered 695 a second, and the queue in oha grew to a p50 of 5.4 s. At 2,000, 36,454 of 59,999 requests failed, nearly all as "connection error". Reading a failed run:
  - when the rate wasn't kept, the percentiles leave out the requests never sent;
  - when requests fail, the percentiles cover what oha timed, so a p50 of 479 ms beside 61% of failures says little.
- **Both Go servers kept every rate,** with a p50 within 2.2 ms of the 240 ms due.

## The first numbers

Plan step 1.8's numbers are made on the machine the owner names, with one command. On that machine:

1. **Get the repository,** and Docker with Compose. Docker 28.0.4 with Compose 2.38.2, and Docker 29.5.2 with Compose 5.5.1, are known to work ([gates](gates.md#in-ci)).
2. **Copy `.env.example` to `.env`,** and describe the host in `BENCH_MACHINE`, such as `BENCH_MACHINE="Ryzen 7 7700, 8 cores, 32 GB, Ubuntu 24.04, native Docker"`. Docker can't always see its host.
3. **Check the backends:** `docker compose run --rm conformance`. It builds every image, and prints how late the machine's timers wake.
4. **Stop everything else on the machine, then run:** `docker compose run --rm runner`. It takes about 25 minutes, writes 36 files in `runs/`, and ends with the table.
5. **Commit the new files in `runs/`,** and write the table into this page, under a heading with the date and the machine. On Linux the files belong to root, since the runner's container runs as root; git reads them all the same.

Numbers from different machines are never compared ([0008](../spec/decisions/0008-run-anywhere-with-docker-and-record-the-machine.md)). Timing numbers from a machine that runs Docker in a VM, such as a Mac, are for development ([0015](../spec/decisions/0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)).
