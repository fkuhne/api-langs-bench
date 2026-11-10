# The conformance suite

One command checks that every backend answers the same requests the same way (R1), and that its fake keeps the contract's pace (R3):

```text
docker compose run --rm conformance
```

pytest's options may follow, such as `-k go-gin` for one backend. Why it's built this way is in [0017](../spec/decisions/0017-the-conformance-suite-pytest-that-drives-compose-and-a-pace-rule-from-the-machines-timers.md).

## How it works

- **Compose starts the three backends first,** building any image that's missing. After a backend's code changes, run `docker compose build` first.
- **The suite restarts each backend itself,** with the settings each check needs, through Docker's socket. That socket gives its container root on Docker's host. At the end, each backend is left running with the settings `.env` gives.
- **The checks** are in [`bench/conformance/`](../bench/conformance/), each run against each backend. Their parts are in [`bench/bench/`](../bench/bench/), with unit tests under `bench-checks`:
  - [`sse.py`](../bench/bench/sse.py) reads the stream strictly, and stamps each event with its arrival;
  - [`fake.py`](../bench/bench/fake.py) works out what the fakes answer, from the contract's rules. It's checked against the examples on the contract's page;
  - [`pace.py`](../bench/bench/pace.py) holds the pace rule and the timer probe;
  - [`compose.py`](../bench/bench/compose.py) drives Compose.

## What it checks

288 checks, 96 for each backend:

| Group | Settings | What |
|---|---|---|
| Health | The defaults | Liveness and readiness |
| The answer | The defaults | The contract's example, whole and streamed. `max_tokens`: 14 values, of which only a smaller positive whole number cuts the answer. Wrapping past the 175th token. `prompt_tokens`, with a non-breaking space and other white space. Other fields ignored. `done` against the whole answer |
| Errors | The defaults | 19 invalid bodies on both paths, each answering 422. Each `fake_error` status, whole and streamed, at once and after 2 tokens. 11 malformed `fake_error`s, each answering 502 |
| The pace | Paced: the first token at 100 ms, then one every 20 ms; 2 reasoning tokens, then 40 answer tokens | The reasoning, whole and streamed. The pace rule on a stream of 42 events. The whole answer, a failure and a malformed `fake_error`, each at its time |
| Settings | Invalid | `FAKE_ANSWER_TOKENS=0`, `FAKE_TOKEN_GAP_MS=soon` and `LLM_PROVIDER=psychic` each stop the start-up |

Every body and every event is also validated against the contract's schemas. Every stream is held to the wire format, its headers and its events' order.

**Not checked:** a client that leaves, readiness answering 503, and the logs of a refused start-up ([0017](../spec/decisions/0017-the-conformance-suite-pytest-that-drives-compose-and-a-pace-rule-from-the-machines-timers.md)).

## The pace rule

An event's lateness is when it arrives, after the request was sent, less its due time. A paced stream passes three checks:
- **No event early,** by any amount.
- **Lateness doesn't add up:** the median lateness of the last quarter of events is within T of the first quarter's.
- **The median lateness is within T.**

**T is the machine's timer error plus a margin of 10 ms.** The timer error is the p99 lateness of a probe the suite runs first, in its own container: 200 sleeps, each to a deadline 10 ms after the last one's. A single event, such as the whole answer, is asked for 5 times, and its median lateness must be within T. The timed stream is a backend's second: its first request on a new connection took 7 to 12 ms to send its headers, against 1 to 2 ms afterwards, and that isn't the fake's pace.

**Why 10 ms, not 5.** With a margin of 5 ms, the first run failed the Python backend, which is correct, twice: a failure due at 160 ms came 7.7 and 12.0 ms late at the median, against a T of 7.6 ms. A single event after a long wait is later than the probe's sleeps: 20 requests each, measured after that run, gave these medians:

| Answer | Python, FastAPI | Go, `net/http` |
|---|---|---|
| The whole answer, due at 180 ms | 8.4 ms late | 6.6 ms late |
| A failure, whole, due at 160 ms | 10.1 ms late | 6.7 ms late |
| A failure, streamed, due at 160 ms | 7.4 ms late | 5.4 ms late |
| A malformed `fake_error`, due at once | 0.7 ms | 0.9 ms |

The likely cause is that the event crosses two late wake-ups in Docker's VM, the backend's timer and the client's read, while the probe times one. That's unchecked. The margin is a development machine's; whether it can shrink on native Linux is checked on the report's machine ([0015](../spec/decisions/0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)).

## Measured on 2026-11-09

**The machine:**
- **Host:** an Apple M3 with 8 cores and 8 GB, on macOS 14.3.
- **Docker:** Docker 29.5.2 and Compose 5.5.1, in Colima's VM: aarch64, 4 CPUs, 5 GiB, Ubuntu 24.04.4. The suite's container runs Compose 5.1.4.
- **Load:** nothing else was running in Docker.

**Ten runs in a row** of `docker compose run --rm conformance -q`, timed from the host, all three backends with their in-process fakes:

| What | Result |
|---|---|
| Checks | 288 passed, in 10 runs out of 10 |
| Time | 52 to 61 s a run; pytest's own, 48 to 57 s |
| The timer probe | Median lateness 1.93 to 2.07 ms; p99 2.58 to 8.34 ms; so T was 12.6 to 18.3 ms |
| Python's stream of 42 events | Median lateness 4.52 to 7.48 ms |
| `net/http`'s | 4.14 to 5.00 ms |
| Gin's | 3.24 to 5.06 ms |

Over the ten runs, the last quarter's lateness was between 1.1 ms earlier and 1.7 ms later than the first quarter's. Single events came up to 25.2 ms late, which the medians ride out. Each stream's headers came within 4.9 ms. These are a development machine's timings, not results ([0015](../spec/decisions/0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)).

**Python times each event closely enough.** The suite's client, in Python, saw every backend's median lateness within 7.5 ms on this Mac, and failed a fake that drifts, below. That closes [0012](../spec/decisions/0012-write-the-evaluation-tool-in-python-apart-from-the-load-generator.md)'s open question at a 20 ms gap.

**Each check fails when it should.** Mistakes were planted in the Go backends on purpose, in three batches, the suite run with `-k go-`, and the mistakes removed:

| Planted mistake | What failed |
|---|---|
| The fake sleeps one gap after each token, instead of waiting for each token's time | The pace check, on both servers: the median lateness was 62.0 and 58.5 ms, and the last quarter came 95.7 and 92.1 ms later than the first |
| `prompt_tokens` splits words on all white space | The non-breaking space and the other white space, on both servers |
| `FAKE_ANSWER_TOKENS=0` accepted | That setting's check, on both servers |
| `net/http` ends its lines with a carriage return and a line feed | Every one of its streams: 52 checks |
| Gin flushes only when the stream ends | Its pace check alone: the median lateness was 415.8 ms. The content checks passed, as they should |
| The whole answer is one token short | 50 checks, on both servers |

**Disk:** the conformance image is 128.6 MB compressed, against 100.2 MB for the checks image it's built on. Docker's images take 29.01 GB in all, 0.8 GB more than before this step.
