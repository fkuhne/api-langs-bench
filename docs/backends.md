# The backends

Three backends serve [the contract](../contract/README.md) so far: Python on FastAPI, Go on its standard library's `net/http`, and Go on Gin. This page says:
- **how each is set up,** and which documentation that set-up follows. Each must be written the way its ecosystem recommends for production, so none wins or loses by an unusual configuration (R6);
- **what was measured when each was built:** its image's size, how fast it starts, what it uses when idle, and how well its fake keeps time.

These are each step's checks, on a development Mac, with every backend answering from the fake inside it. They aren't the benchmark's results: those come from [the runner](runner.md). The words used here, such as pace and in-process fake, are explained in [the guide](README.md#the-words-used-here).

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
- **The fake's clock** is `time.monotonic()`, not the event loop's: uvloop's `loop.time()` counts whole milliseconds, and read 0.7 to 2.0 ms behind it (our run in the backend's image, 2026-11-10). The fake waits again when the loop wakes before a token's time ([0022](../spec/decisions/0022-the-python-fake-keeps-time-on-the-systems-monotonic-clock-not-uvloops.md)).
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

## Go: net/http

[`backends/go/`](../backends/go/), its routes in [`internal/nethttp/`](../backends/go/internal/nethttp/server.go), built in the first half of plan step 1.4 ([0016](../spec/decisions/0016-two-go-backends-net-http-and-gin-in-one-module.md)).

**How it's set up:**
- **Versions:** Go 1.27.3, with the standard library alone.
- **Shared with the Gin backend:** the settings, the LLM port and its errors, the fake, and the start-up, in [`internal/`](../backends/go/internal/). So are the contract's checks, in [`internal/apitest/`](../backends/go/internal/apitest/apitest.go), which each server's tests run.
- **The routes:** `ServeMux` with method patterns, and `encoding/json`. The stream's status and headers go as soon as the body is valid. Then each event is written by hand and flushed through `http.ResponseController`.
- **The server:** an `http.Server` with a 10 s `ReadHeaderTimeout` and no write timeout. On SIGTERM it stops taking requests, and gives open ones 10 s.
- **The image:** built with `CGO_ENABLED=0 GOOS=linux go build`, as [Docker's guide](https://docs.docker.com/guides/golang/build-images/) does. It runs on distroless's static Debian 13 image as `nonroot`, pinned by digest. Compose's healthcheck runs the binary's own `healthcheck` command, since the image has no shell.
- **One process,** with Go's defaults, until plan step 3.1's rule. `net/http` writes no access log.
- **Started with** `docker compose up -d --wait go-nethttp`, on `127.0.0.1:8002`.

**Measured on 2026-11-09, beside the Python backend.** Both were measured in the same session, one after the other, on the machine named at the top of this page:

| What | Python, FastAPI | Go, `net/http` | How |
|---|---|---|---|
| Image, unpacked | 180.5 MiB | 12.8 MiB | A container's `docker export`, in bytes. Step 1.3's 193 MiB was `du -sx /`, which counts disk blocks |
| Image, compressed | 56.6 MB | 6.5 MB | `docker image inspect` |
| Start-up | Ready 0.73 s after `docker compose up -d` began: median of 5, 0.68 to 0.74 | 0.17 s: 0.15 to 0.21 | The host polls `/api/health/ready` every 10 ms. Go's very first start, the image just built, took 1.15 s |
| Idle memory | 44.7 MiB, 0.46% CPU, 6 tasks | 2.1 MiB, 0.00% CPU, 8 tasks | `docker stats --no-stream`, 8 s after the last start |
| Liveness | Median 0.7 ms, then 0.6 ms | 0.5 ms, then 0.7 ms | 50 requests, each on a new connection, from a container on Compose's network, in two rounds |
| Stream's headers | At 10 ms | At 4 ms | curl's `time_starttransfer`, with the first token due at 100 ms |
| Gates | 72 tests, 100% coverage | 0 issues, 92.6% coverage of all of `backends/go/` | Each language's `-checks` service |

**The answers match the contract's page, byte for byte.** The example request gets the contract's whole answer, and its stream to the byte, with `Cache-Control: no-cache`. A reserved key gets a 422. `fake_error` with 503 after one token gets one `token` event, then `error` with status 503. `encoding/json` writes `<` as `\u003c` and `&` as `\u0026`, as the contract's page says.

**The pace,** with `FAKE_FIRST_TOKEN_MS=100` and `FAKE_TOKEN_GAP_MS=20`. Each cell is the median of ten streams of ten tokens, or of ten whole answers, in each of two rounds:

| Backend | Measured from | First token (want 100 ms) | Gap (want 20 ms) | Whole answer (want 280 ms) |
|---|---|---|---|---|
| Python, FastAPI | The host | 111.9, then 113.3 ms | 20.4, then 19.3 ms | 291.4, then 290.2 ms |
| Go, `net/http` | The host | 108.5, then 111.8 ms | 20.3, then 19.9 ms | 290.1, then 292.7 ms |
| Python, FastAPI | A container on Compose's network | 108.6, then 115.5 ms | 19.8, then 19.2 ms | 291.0, then 293.0 ms |
| Go, `net/http` | A container on Compose's network | 109.8, then 108.5 ms | 20.1, then 20.2 ms | 291.1, then 290.9 ms |

- **On this machine, the pace can't tell the two apart.** Both carry the VM's late wake-ups, about 10 ms on the first token ([0015](../spec/decisions/0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)). Go's timers don't escape them.
- **Single gaps range from 0 to 45 ms** in both, around a 20 ms median: a late token is followed by a short gap.

**A client that leaves.** In the shared test, the client leaves a stream after two tokens, at a 20 ms gap, served over a real socket. The fake made at most one more token, in 20 runs out of 20, against FastAPI's three. `net/http` cancels the request's context 0.2 ms after the client closes its connection, measured with a raw TCP client.

**Go's own HTTP client leaves late.** When a response's body is closed early, Go 1.27.3's client reads on for up to 50 ms or 256 KiB, hoping to reuse the connection, and only then closes it (`maxPostCloseReadTime` and `maxPostCloseReadBytes`, in `net/http/transport.go`). Measured with it, the server's context was cancelled 51 ms after the client called `Close`. The test's client turns keep-alive off, so it closes its connection at once.

<details>
<summary>The pace probe, and how it was run</summary>

```python
"""Step 1.3's pace and liveness probe, for any backend: python paceprobe.py HOST PORT [LIVENESS]."""
import http.client, json, statistics, sys, time

HOST, PORT = sys.argv[1], int(sys.argv[2])
LIVENESS = len(sys.argv) > 3
BODY = json.dumps({"messages": [{"role": "user", "content": "Hi"}], "parameters": {"max_tokens": 10}})


def event_name(line):
    """The event's name, by the SSE rules: `event:`, then one optional space."""
    name = line.rstrip(b"\r\n")[len(b"event:"):]
    return name[1:] if name.startswith(b" ") else name


def stream():
    c = http.client.HTTPConnection(HOST, PORT); t0 = time.perf_counter()
    c.request("POST", "/api/chat/stream", BODY, {"Content-Type": "application/json"})
    r = c.getresponse(); times = []
    while line := r.readline():
        if line.startswith(b"event:") and event_name(line) == b"token":
            times.append(time.perf_counter() - t0)
    c.close(); return times


def whole():
    c = http.client.HTTPConnection(HOST, PORT); t0 = time.perf_counter()
    c.request("POST", "/api/chat", BODY, {"Content-Type": "application/json"}); c.getresponse().read()
    t = time.perf_counter() - t0; c.close(); return t


def health():
    c = http.client.HTTPConnection(HOST, PORT); t0 = time.perf_counter()
    c.request("GET", "/api/health"); c.getresponse().read(); t = time.perf_counter() - t0; c.close(); return t


stream(); whole(); health()  # warm up the connection path
ttft, gaps, wholes = [], [], []
for _ in range(10):
    t = stream(); assert len(t) == 10, t
    ttft.append(t[0]); gaps += [b - a for a, b in zip(t, t[1:])]; wholes.append(whole())
ms = lambda xs: f"median {statistics.median(xs)*1000:.1f} ms, min {min(xs)*1000:.1f}, max {max(xs)*1000:.1f}"
print(f"{HOST}:{PORT}, 10 streams of 10 tokens, 10 whole answers:")
print("  time to first token (want 100):", ms(ttft))
print("  gap between tokens (want 20):  ", ms(gaps), f"({len(gaps)} gaps)")
print("  whole answer (want 280):       ", ms(wholes))
if LIVENESS:
    lives = [health() for _ in range(50)]
    print("  liveness, 50 requests, new connection each:", ms(lives))
```

```sh
FAKE_FIRST_TOKEN_MS=100 FAKE_TOKEN_GAP_MS=20 docker compose up -d --wait python-fastapi go-nethttp
# From the host, through Colima's port forwarding:
python3 -I paceprobe.py 127.0.0.1 8001
python3 -I paceprobe.py 127.0.0.1 8002
# From a container on Compose's network:
docker run --rm -i --network api-langs-bench_default python:3.14.8-slim-trixie \
  python - go-nethttp 8000 liveness < paceprobe.py
```

</details>

## Go: Gin

[`backends/go/`](../backends/go/), its routes in [`internal/ginserver/`](../backends/go/internal/ginserver/server.go), built in the second half of plan step 1.4 ([0016](../spec/decisions/0016-two-go-backends-net-http-and-gin-in-one-module.md)). It shares everything but its routes with the `net/http` backend, and passes the same contract checks.

**How it's set up:**
- **Versions:** Gin v1.12.0, on Go 1.27.3. Its JSON is `encoding/json`, Gin's default without build tags.
- **The routes:** `gin.Default()`, with Gin's logger and recovery. The router trusts no proxy, as Gin's warning asks, since none stands in front of it. Requests are bound with `ShouldBindJSON` and `binding` tags, checked by go-playground's validator. Answers are written with `c.JSON`.
- **The stream:** the status and headers go as soon as the body is valid. Then each event is written with `c.SSEvent`, and flushed. Gin writes `event:token` and `data:{…}`, with no space after the colon, which the SSE standard allows.
- **Release mode:** `GIN_MODE=release`, set in the image, as Gin's own warning asks for production. Gin's deployment page lists the variable without recommending a mode.
- **The access log:** Gin's logger writes a line per request to stdout, as uvicorn does. `net/http` writes none. All three keep their defaults until plan step 3.1's rule.
- **The binary** is 28.7 MiB, against `net/http`'s 9.6 MiB. Gin links every codec it can bind or render, used or not: YAML, TOML, protobuf, msgpack and BSON. It also links HTTP/3's quic-go (`go version -m`).
- **The image, the server and the healthcheck** are the `net/http` backend's.
- **Started with** `docker compose up -d --wait go-gin`, on `127.0.0.1:8003`.

**Measured on 2026-11-09, beside the other two.** All three were measured in one session, after the `net/http` backend's table above:

| What | Python, FastAPI | Go, `net/http` | Go, Gin | How |
|---|---|---|---|---|
| Image, unpacked | 180.5 MiB | 12.8 MiB | 31.9 MiB | A container's `docker export`, in bytes |
| Image, compressed | 56.6 MB | 6.5 MB | 16.3 MB | `docker image inspect` |
| Start-up | Ready 0.72 s after `docker compose up -d` began: median of 5, 0.69 to 0.96 | 0.18 s: 0.17 to 0.22 | 0.23 s: 0.18 to 0.30 | The host polls `/api/health/ready` every 10 ms |
| Idle memory | 44.7 MiB, 1.48% CPU, 6 tasks | 2.0 MiB, 0.00% CPU, 8 tasks | 2.6 MiB, 0.00% CPU, 8 tasks | `docker stats --no-stream`, 8 s after the last start |
| Liveness | Median 0.6 ms | 0.6 ms | 0.7 ms | 50 requests, each on a new connection, from a container on Compose's network |
| Stream's headers | At 10 ms | At 5 ms | At 14 ms | curl's `time_starttransfer`, with the first token due at 100 ms |
| A client that leaves | At most 3 more tokens | At most 1 | At most 1 | Each backend's test, 20 runs out of 20 |

**The answers match the contract's page** once parsed, by its rules: the same JSON whole, and the same events, `event:token` written without a space. A reserved key and an unknown role get a 422, with the validator's message as the `detail`. `fake_error` with 503 after one token gets one `token` event, then `error` with status 503.

**The pace,** with `FAKE_FIRST_TOKEN_MS=100` and `FAKE_TOKEN_GAP_MS=20`, measured with the probe above. Each cell is the median of ten streams of ten tokens, or of ten whole answers:

| Backend | Measured from | First token (want 100 ms) | Gap (want 20 ms) | Whole answer (want 280 ms) |
|---|---|---|---|---|
| Python, FastAPI | The host | 117.2 ms | 19.9 ms | 293.4 ms |
| Go, `net/http` | The host | 108.0 ms | 19.5 ms | 294.0 ms |
| Go, Gin | The host | 113.6 ms | 19.0 ms | 291.3 ms |
| Python, FastAPI | A container on Compose's network | 110.8 ms | 20.4 ms | 290.1 ms |
| Go, `net/http` | A container on Compose's network | 108.4 ms | 20.1 ms | 287.1 ms |
| Go, Gin | A container on Compose's network | 109.6 ms | 19.7 ms | 293.4 ms |

**What these step checks show, on this machine:**
- **Size, start-up and idle memory** set Go apart from Python by about ten times. Gin costs more than `net/http` in size, through its dependencies, and a little in memory and start-up.
- **The pace and liveness don't set any of them apart here.** The VM's late wake-ups are larger than what each adds ([0015](../spec/decisions/0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)). The benchmark's own runs start at plan step 1.6.

## The upstream client

Built in plan step 2.2 ([0024](../spec/decisions/0024-each-backends-upstream-client-its-plain-http-client-one-pool-setting-no-retries.md)). With `LLM_PROVIDER=openai-compatible`, a backend stops answering from the fake inside it, and calls an upstream over HTTP: the [fake server](fake-server.md) for now. The upstream client is the code that makes that call. What it must do is in [the contract](../contract/README.md#the-upstream), the same for every backend. Each is written with its ecosystem's plain HTTP client, not an OpenAI SDK.

| | Python, FastAPI | Go, `net/http` and Gin |
|---|---|---|
| The code | [`app/upstream/`](../backends/python-fastapi/app/upstream/) | [`internal/upstream/`](../backends/go/internal/upstream/), shared by both backends |
| The HTTP client | httpx2 2.13.1, which the OpenAI SDK runs on too | `net/http`, from a copy of Go's default transport |
| The pool | `Limits(max_connections, max_keepalive_connections)`, both at `LLM_MAX_CONNECTIONS` | `MaxConnsPerHost`, `MaxIdleConnsPerHost` and `MaxIdleConns`, all at `LLM_MAX_CONNECTIONS` |
| An idle connection is kept | 5 s, httpx2's default | 90 s, Go's default |
| The timeout | `Timeout(LLM_TIMEOUT_SECONDS)`: httpx2 applies it to each wait | A timer the client starts again each time something arrives. Go's own `Client.Timeout` would bound the whole answer |
| The stream is read | Line by line, with `aiter_lines`, each chunk parsed with `json.loads` | Line by line, with `bufio.Scanner`, each chunk decoded into a struct with `encoding/json` |
| A client that leaves | Closing the generator closes the response | The request's context ends, then the body is closed. Without the first, Go's client reads on for up to 50 ms |
| Tests | 67, against httpx2's mock transport | 18, with 40 cases inside them, against a real server on a local socket |

**Checked through the fake server, on 2026-11-10,** on the Mac named at the top of this page, each backend under 1 CPU and 512 MiB, with the fake server paced at 50 ms and 10 ms:

| Check | Python, FastAPI | Go, `net/http` | Go, Gin |
|---|---|---|---|
| A stream of 150 tokens, 1.54 s long, under a timeout of 1 s | Ended with `done`, at 1.56 s | At 1.55 s | At 1.54 s |
| The client leaves at 120 ms: when the fake server saw its stream closed, from its own start | 114.6 ms, 7 tokens sent | 118.4 ms, 7 tokens | 131.8 ms, 9 tokens |
| Readiness | `{"status":"ok","checks":{"llm":"ok"}}` | The same | The same |

- **The timeout doesn't cut a long stream,** in either language.
- **Each backend closes the upstream's connection when its client leaves.** Gin's was seen about 13 ms later than the others', once. How fast each does it under load is plan step 3.3.

**A first look under load,** to see that the client holds: the `stream-20` request at fixed rates for 15 s, with oha, on the same busy Mac. Nothing was saved as a run, so these are a sketch, not results; plan step 2.4 measures it.

| Backend | Rate | p50 | p99 | Its CPU | The fake server's CPU |
|---|---|---|---|---|---|
| Python, FastAPI | 100/s | 244.5 ms | 250.7 ms | 41% of one CPU | 10% |
| Python, FastAPI | 300/s | 244.4 ms | 375.6 ms | 91% | 14% |
| Python, FastAPI | 500/s | 3,183.6 ms: it answered 341 a second | | 101% | 13% |
| Go, `net/http` | 100/s | 242.4 ms | 255.3 ms | 31% | 17% |
| Go, `net/http` | 1,000/s | 241.5 ms | 278.4 ms | 83% | 48% |
| Go, `net/http` | 2,000/s | 242.7 ms | 395.2 ms | 95% | 62% |
| Go, Gin | 100/s | 242.6 ms | 255.8 ms | 37% | 24% |
| Go, Gin | 1,000/s | 241.5 ms | 251.4 ms | 80% | 43% |
| Go, Gin | 2,000/s | 241.9 ms | 268.8 ms | 98% | 54% |

- **Calling an upstream costs each backend a large share of its CPU.** From their in-process fakes, on this Mac, Python kept 500 a second and Go 4,000 ([runner](runner.md)). Through the fake server, Python ran out between 300 and 500, and both Go servers were at the end of their CPU at 2,000.
- **The fake server stayed far from its own ceiling,** at 62% of a CPU or less.
- **CPU doesn't grow in step with the rate on this VM:** Go's was 31% at 100 a second and 83% at 1,000. An idle virtual CPU costs more to wake ([below](#where-the-delay-comes-from)).

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
