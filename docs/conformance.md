# The conformance suite

A benchmark that compares backends is only fair if each does exactly the same work. The conformance suite is what shows it. One command sends every backend the same requests, and checks two things:
- **each answers the same way,** to the contract's letter: the same statuses, the same events, the same texts (R1);
- **each one's fake keeps the contract's pace:** every token arrives at its time, never early, and never later than the machine's own timers explain (R3).

Each backend is checked twice: answering from the fake inside it, and passing on the fake server's answer through its upstream client. The fake upstream server is checked alone too. The words used here, such as pace and lateness, are explained in [the guide](README.md#the-words-used-here).

```text
docker compose run --rm conformance
```

pytest's options may follow, such as `-k go-gin` for one backend. Why it's built this way is in [0017](../spec/decisions/0017-the-conformance-suite-pytest-that-drives-compose-and-a-pace-rule-from-the-machines-timers.md).

## How it works

- **Compose starts the three backends and the fake server first,** building any image that's missing. After their code changes, run `docker compose build` first.
- **The suite restarts each of them itself,** with the settings each check needs: the fakes' pace is a setting, read at start-up. It does so through Docker's socket, which gives its container root on Docker's host. At the end, each is left running with the settings `.env` gives.
- **Each backend runs twice:** with `LLM_PROVIDER=fake`, and with `LLM_PROVIDER=openai-compatible` and the fake server as its upstream, both started with the same settings. Through the fake server, a backend must answer what it answers alone, except for the model's name, `fake-server`.
- **The checks** are in [`bench/conformance/`](../bench/conformance/), each run against each backend from each upstream. Their parts are in [`bench/bench/`](../bench/bench/), with unit tests under `bench-checks`:
  - [`sse.py`](../bench/bench/sse.py) reads the stream strictly, and stamps each event with its arrival;
  - [`fake.py`](../bench/bench/fake.py) works out what the fakes answer, from the contract's rules. It's checked against the examples on the contract's page;
  - [`pace.py`](../bench/bench/pace.py) holds the pace rule and the timer probe;
  - [`compose.py`](../bench/bench/compose.py) drives Compose.

## What it checks

627 checks: 99 for each backend from each of its two upstreams, and 33 for the fake server alone ([below](#the-fake-server-alone)). 21 more, through llama.cpp's real model, run only when asked, with `-m llama_cpp` ([llama.cpp](llama-cpp.md#checked-by-the-conformance-suite)). For each backend, from each upstream:

| Group | Settings | What |
|---|---|---|
| Health | The defaults | Liveness and readiness |
| The answer | The defaults | The contract's example, whole and streamed. `max_tokens`: 14 values, of which only a smaller positive whole number cuts the answer. Wrapping past the 175th token. `prompt_tokens`, with a non-breaking space and other white space. Other fields ignored. `done` against the whole answer |
| Errors | The defaults | 19 invalid bodies on both paths, each answering 422. Each `fake_error` status, whole and streamed, at once and after 2 tokens. 11 malformed `fake_error`s, each answering 502 |
| The pace | Paced: the first token at 100 ms, then one every 20 ms; 2 reasoning tokens, then 40 answer tokens | The reasoning, whole and streamed. The pace rule on a stream of 42 events. The whole answer, a failure and a malformed `fake_error`, each at its time |
| Settings | Invalid | `FAKE_ANSWER_TOKENS=0`, `FAKE_TOKEN_GAP_MS=soon`, `LLM_PROVIDER=psychic`, `LLM_BASE_URL=fake-server:8080`, `LLM_TIMEOUT_SECONDS=0` and `LLM_MAX_CONNECTIONS=0` each stop the start-up |

Every body and every event is also validated against the contract's schemas. Every stream is held to the wire format, its headers and its events' order.

**Through the fake server,** the backend waits 1 s for its upstream, not 300, so each check of a `fake_error` of 504, which makes the fake server go silent, takes about a second.

### The fake server alone

33 checks in [`test_fake_server.py`](../bench/conformance/test_fake_server.py), sent as a backend's client would send them ([0023](../spec/decisions/0023-the-fake-upstream-server-go-in-its-own-module-shaped-as-llama-cpps-chunks.md), [the contract](../contract/README.md#the-fake-server)):

| Group | Settings | What |
|---|---|---|
| The answer | The defaults, then paced | A stream's tokens, finish reason and usage against the contract's, with three values of `max_tokens`. Its first and last chunks. The usage, only when asked for. A whole answer, with its reasoning |
| The pace | Paced, as for the backends | The pace rule on a stream of 42 tokens, whose headers must not come before the first token's time. A whole answer at the last token's time |
| Failures | The defaults, then paced | Each `fake_error` status as a plain HTTP error, whole and streamed, and as an error chunk after 2 tokens. A 504 as half a second of silence, at once and after a token. 4 malformed `fake_error`s, refused before the first token's time. 3 bodies it can't read |
| The rest | The defaults, then paced | Its health. A client that leaves after two tokens, and the line logged for it |

These read the fake server's JSON loosely: its fields are held to llama.cpp's by its own tests ([fake server](fake-server.md#how-its-built)).

**Not checked:** a client that leaves a backend, readiness answering 503, and the logs of a refused start-up ([0017](../spec/decisions/0017-the-conformance-suite-pytest-that-drives-compose-and-a-pace-rule-from-the-machines-timers.md)).

## The pace rule

An event's lateness is when it arrives, after the request was sent, less its due time. With the first token due at 100 ms, one that arrives 101.3 ms after the request went is 1.3 ms late. A paced stream passes three checks:
- **No event early,** by any amount.
- **Lateness doesn't add up:** the median lateness of the last quarter of events is within T of the first quarter's.
- **The median lateness is within T.**

**Behind the fake server, T is 5 ms wider.** There an event crosses one more late wake-up, the backend's read of the upstream's chunk ([0024](../spec/decisions/0024-each-backends-upstream-client-its-plain-http-client-one-pool-setting-no-retries.md)).

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

## In CI, on 2026-11-10

On GitHub's `ubuntu-24.04` runner: x86-64, 4 CPUs, 16 GB, Docker 28.0.4 and Compose 2.38.2 ([gates](gates.md#in-ci)). Three attempts of [run 42745505829](https://github.com/fkuhne/api-langs-bench/actions/runs/42745505829):

| | Attempt 1 | Attempt 2 | Attempt 3 |
|---|---|---|---|
| Checks | 288 passed in 52.6 s | 288 passed in 56.4 s | 288 passed in 56.0 s |
| The timer probe, median / p99 | 0.09 / 0.09 ms late | 0.11 / 0.13 ms | 0.08 / 0.14 ms |
| Python's stream, median lateness | 1.15 ms | 2.05 ms | 2.58 ms |
| `net/http`'s | 1.19 ms | 1.31 ms | 1.55 ms |
| Gin's | 1.13 ms | 1.38 ms | 1.60 ms |
| The last quarter on the first, widest | +0.16 ms | +0.11 ms | -0.03 ms |

- **Linux's timers in a cloud VM are 20 times tighter than Docker's VM on the Mac:** 0.1 ms late against about 2 ms. The streams came 1 to 3 ms late, against 4 to 8 ms on the Mac.
- **So the 10 ms margin is loose there.** T was 10.1 ms, and every backend's median lateness was below 2.6 ms. A fake that sleeps one gap after each token would drift by its own overhead on each token, about 0.1 ms here (computed), or 3 ms over a stream. That passes a T of 10 ms. Whether the margin should shrink on Linux stays open in [0017](../spec/decisions/0017-the-conformance-suite-pytest-that-drives-compose-and-a-pace-rule-from-the-machines-timers.md).

## Python's fake sent tokens early, on 2026-11-10

The same runner, later that day: both attempts of [run 42830465967](https://github.com/fkuhne/api-langs-bench/actions/runs/42830465967), on a commit that changed no backend, failed one check of 288, `test_the_stream_keeps_the_pace[python-fastapi]`.

| | Attempt 1 | Attempt 2 | Four earlier runs that passed |
|---|---|---|---|
| The timer probe, median / p99 | 0.07 / 0.08 ms late | not read | 0.08 to 0.11 ms at the median |
| Python's stream, median lateness | 0.68 ms | 0.82 ms | 1.14 to 2.58 ms |
| Python's stream, smallest lateness | -0.18 ms | -0.16 ms | 0.15 to 1.96 ms |
| Events early, of 42 | 3, by 0.10 to 0.18 ms | at least 1 | none |
| `net/http`'s smallest lateness | 0.64 ms | not read | not read |

- **The pace rule caught a real fault,** not a flaky check: Python's fake counted its deadlines on uvloop's clock, which counts whole milliseconds and runs up to 2 ms behind the system's. A faster machine, with less time between the client and the backend, let it show.
- **The Mac never showed it:** its late timers cover a millisecond many times over.
- **The fix** is in [0022](../spec/decisions/0022-the-python-fake-keeps-time-on-the-systems-monotonic-clock-not-uvloops.md): the fake reads the system's monotonic clock, and waits again when the event loop wakes early.

**After the fix,** three attempts of [run 42839239272](https://github.com/fkuhne/api-langs-bench/actions/runs/42839239272), on commit `72fdaf1`: 288 checks passed in each.

| | Attempt 1 | Attempt 2 | Attempt 3 |
|---|---|---|---|
| The timer probe, median / p99 | 0.11 / 0.12 ms late | 0.07 / 0.15 ms | 0.11 / 0.12 ms |
| Python's stream, median lateness | 2.02 ms | 2.21 ms | 1.93 ms |
| Python's stream, smallest lateness | 1.57 ms | 1.64 ms | 1.50 ms |
| `net/http`'s, median / smallest | 1.34 / 0.83 ms | 1.27 / 0.79 ms | 1.25 / 0.74 ms |
| Gin's, median / smallest | 1.26 / 0.72 ms | 1.35 / 0.88 ms | 1.31 / 0.79 ms |

- **No event early,** in any attempt.
- **Python's tokens now come 0.6 to 0.9 ms after Go's** at the median. That's what a clock of whole milliseconds costs: a wait ends at uvloop's first millisecond past the token's time.

## Through the fake server, on 2026-11-10

Plan step 2.2 gave each backend its upstream client ([0024](../spec/decisions/0024-each-backends-upstream-client-its-plain-http-client-one-pool-setting-no-retries.md)). On the Mac, with the host busy (a load average of 3 to 5): 627 checks passed, in 177.77 s. The lines on the pace:

```text
the machine's timers: 200 sleeps of 10 ms woke 2.06 ms late at the median, 5.19 ms at the p99; tolerance 15.19 ms (the p99 plus 10 ms)
fake-server: 42 tokens, lateness median 6.09 ms, min 3.22, max 15.37; the last quarter -0.31 ms on the first; headers at 108.9 ms
python-fastapi: 42 events, lateness median 9.83 ms, min 6.95, max 19.49; the last quarter -0.22 ms on the first; headers at 7.5 ms
python-fastapi via fake-server: 42 events, lateness median 18.58 ms, min 16.29, max 36.38; the last quarter +0.37 ms on the first; headers at 11.2 ms
go-nethttp: 42 events, lateness median 4.78 ms, min 1.83, max 9.93; the last quarter +1.00 ms on the first; headers at 1.6 ms
go-nethttp via fake-server: 42 events, lateness median 9.12 ms, min 6.67, max 11.69; the last quarter +0.82 ms on the first; headers at 1.4 ms
go-gin: 42 events, lateness median 4.36 ms, min 1.98, max 16.15; the last quarter +0.75 ms on the first; headers at 1.7 ms
go-gin via fake-server: 42 events, lateness median 6.76 ms, min 5.34, max 18.93; the last quarter +0.34 ms on the first; headers at 1.7 ms
```

- **Every backend answers through the fake server what it answers alone:** the same 99 checks pass from both upstreams.
- **Why the tolerance is wider there.** The run before this one failed one check of 627: Python's stream through the fake server came 17.75 ms late at the median, against a T of 15.34 ms. Both Go servers were close, at 10.36 and 14.13 ms. Behind an upstream, an event crosses three late wake-ups in Docker's VM, not two: the fake server's timer, the backend's read, and the client's read. With 5 ms more, Python's 18.58 ms above is within its T of 20.19 ms.
- **That's the Mac's VM again.** On Linux's timers the margin is loose in both cases; CI's lines will say how late each backend is there.
- **Python is later than Go through the fake server,** by about 9 ms here against 2 to 5 ms alone. One stream at a time, on an idle VM, says little about load; plan step 2.4 measures it.

**In CI, on Linux's timers,** three attempts of [run 42905293392](https://github.com/fkuhne/api-langs-bench/actions/runs/42905293392), on commit `658e24e`: 627 checks passed in each, in 170 to 174 s. The median lateness of each paced stream:

| | Attempt 1 | Attempt 2 | Attempt 3 |
|---|---|---|---|
| The timer probe, median / p99 | 0.09 / 0.09 ms late | 0.09 / 0.10 ms | 0.09 / 0.10 ms |
| The fake server, alone | 1.21 ms | 1.05 ms | 1.29 ms |
| Python, from its own fake | 1.69 ms | 1.73 ms | 1.80 ms |
| Python, through the fake server | 3.33 ms | 3.21 ms | 3.35 ms |
| `net/http`, from its own fake | 1.12 ms | 1.14 ms | 1.11 ms |
| `net/http`, through the fake server | 1.93 ms | 1.98 ms | 1.98 ms |
| Gin, from its own fake | 1.15 ms | 1.11 ms | 1.14 ms |
| Gin, through the fake server | 2.04 ms | 1.95 ms | 2.02 ms |

- **No event early,** from either upstream, in any attempt. The smallest lateness through the fake server was 1.41 ms.
- **Passing an upstream's stream on cost Go about 0.8 ms a token, and Python about 1.6 ms,** one stream at a time, on a shared VM. That's a first sight of what plan step 2.4 measures.
- **The tolerance is loose there,** as before: 15.1 ms behind the fake server, against 3.4 ms at most.
- **The evaluation tool's gates failed in that run,** on a test of the contract page's examples: the page had gained a JSON block, and the examples were found by their position. They're now found by what they hold. The mistake was ours: the gate had been run locally with its result hidden by a pipe.
