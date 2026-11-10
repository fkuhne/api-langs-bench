# The fake upstream server

A backend's job is to call a language model and pass its answer on. To measure what that costs in each language, the model has to be taken out of the picture: a real one takes seconds to answer, and never the same way twice.

The fake upstream server takes its place. It's a small program that answers the way llama.cpp's server does, with the contract's fixed tokens on the contract's timetable. A backend calls it over HTTP with the same client code it calls llama.cpp with. So a run against it measures that client too: opening and reusing connections, reading the stream, and turning each chunk into an event ([0004](../spec/decisions/0004-three-local-upstreams-llama-cpp-a-fake-server-and-an-in-process-fake.md)).

How it's built, and why, is in [0023](../spec/decisions/0023-the-fake-upstream-server-go-in-its-own-module-shaped-as-llama-cpps-chunks.md). It's plan step 2.1, and the backends' clients for it are plan step 2.2. The words used here are explained in [the guide](README.md#the-words-used-here). It starts with:

```text
docker compose up -d --wait fake-server
```

It then answers on `127.0.0.1:8010`, and on Compose's network at `http://fake-server:8080/v1`. `FAKE_SERVER_PORT` in `.env` moves the first.

## How it's built

[`fake-server/`](../fake-server/) is a Go module of its own, with Go's standard library alone. It shares no code with the Go backends.

| Package | What |
|---|---|
| [`internal/chat`](../fake-server/internal/chat/) | The routes: a request's plan ([`plan.go`](../fake-server/internal/chat/plan.go)), llama.cpp's shapes ([`chunks.go`](../fake-server/internal/chat/chunks.go)), and the answer, token by token ([`server.go`](../fake-server/internal/chat/server.go)) |
| [`internal/clock`](../fake-server/internal/clock/) | Go's monotonic clock, and a wait until a time |
| [`internal/settings`](../fake-server/internal/settings/), [`internal/tokens`](../fake-server/internal/tokens/) | The contract's `FAKE_*` settings and its token file |
| [`internal/app`](../fake-server/internal/app/) | The start-up, the stop, and the `healthcheck` command Compose calls |

- **What it answers** is in [the contract](../contract/README.md#the-fake-server): the contract's tokens at the contract's pace, in llama.cpp's chunks, and each `fake_error` as llama.cpp shows a failure.
- **One write for each token.** A token's chunk is put together from parts made once: each token as JSON at start-up, and the fields every chunk ends with once for each answer.
- **A client that leaves** ends its answer at once, and one line is logged, as JSON:

  ```json
  {"time":"2026-11-10T16:19:13.985130714Z","level":"INFO","msg":"closed early","id":"chatcmpl-00000000000000000000000000000005","stream":true,"tokens_sent":4,"after_ms":82.482}
  ```
- **A stop ends every open answer at once,** as if its client had left.
- **No limit on its CPUs or memory** in Compose: it's a helper.
- **Its gates** are `docker compose run --rm fake-server-checks`, the same as the Go backends' ([gates](gates.md)): 0 issues, and 97.7% coverage.

**How close to llama.cpp's it is.** Two tests compare its stream and its whole answer with the capture below, kept in [`testdata/`](../fake-server/internal/chat/testdata/): the same events, each with the same fields, in the same order, with the same kind of value.

| Event | llama.cpp's, bytes | The fake server's |
|---|---|---|
| The role | 274 | 258 |
| A token of one character | 254 | 238 |
| The finish reason | 245 | 229 |
| The usage | 571 | 475 |

The fake server's are 16 bytes shorter where the fields are the same: its model's name and its build's are `fake-server`, against `/models/stories260K.gguf` and `b12242-3b4d6ab3f`. Its usage is shorter because its timings are round numbers.

**What it doesn't imitate:**
- **llama.cpp's `Keep-Alive: timeout=5, max=100`,** which closes a connection idle for 5 s, or used 100 times. Go's server keeps a connection open.
- **`Connection: close` after an error.** llama.cpp closes the connection it refused a request on.
- **llama.cpp's slots,** four in the capture: the fake server answers any number of requests at once.
- **Its other routes,** such as `/v1/models`.

## What llama.cpp sends

What the fake server imitates, captured on 2026-11-10 on the development Mac (Apple M3, Docker 29.5.2 in Colima's VM):
- **The server:** the image `ghcr.io/ggml-org/llama.cpp:server` at digest `sha256:4d2de15a0ffbce704777c64026b40512a71e0bbc0b303a5fe5ea9bf71760dff9`, 291.8 MB, which reports the build `b12242-3b4d6ab3f` and four slots.
- **The model:** [`stories260K.gguf`](https://huggingface.co/ggml-org/models/blob/main/tinyllamas/stories260K.gguf), 1,185,376 bytes. It writes nonsense, quickly, which is enough to see the chunks.
- **The command:** `llama-server -m /models/stories260K.gguf --host 0.0.0.0 --port 8080 -c 512`, then `curl` from a container on the same Docker network.

**A stream,** asked with `"stream": true`, `"stream_options": {"include_usage": true}` and `"max_tokens": 4`. Its headers:

```text
HTTP/1.1 200 OK
Server: llama.cpp
Access-Control-Allow-Origin:
X-Accel-Buffering: no
Content-Type: text/event-stream
Keep-Alive: timeout=5, max=100
Transfer-Encoding: chunked
```

Its eight events, of which the second to the fifth are a token each. The four tokens shown once:

```text
data: {"choices":[{"finish_reason":null,"index":0,"delta":{"role":"assistant","content":null}}],"created":1794319621,"id":"chatcmpl-07HESjGdwl4wxzcWyJxFQJiyrSx1ihdO","model":"/models/stories260K.gguf","system_fingerprint":"b12242-3b4d6ab3f","object":"chat.completion.chunk"}

data: {"choices":[{"finish_reason":null,"index":0,"delta":{"content":"H"}}],"created":1794319621,"id":"chatcmpl-07HESjGdwl4wxzcWyJxFQJiyrSx1ihdO","model":"/models/stories260K.gguf","system_fingerprint":"b12242-3b4d6ab3f","object":"chat.completion.chunk"}

data: {"choices":[{"finish_reason":"length","index":0,"delta":{}}],"created":1794319621,"id":"chatcmpl-07HESjGdwl4wxzcWyJxFQJiyrSx1ihdO","model":"/models/stories260K.gguf","system_fingerprint":"b12242-3b4d6ab3f","object":"chat.completion.chunk"}

data: {"choices":[],"created":1794319621,"id":"chatcmpl-07HESjGdwl4wxzcWyJxFQJiyrSx1ihdO","model":"/models/stories260K.gguf","system_fingerprint":"b12242-3b4d6ab3f","object":"chat.completion.chunk","usage":{"completion_tokens":4,"prompt_tokens":46,"total_tokens":50,"prompt_tokens_details":{"cached_tokens":0}},"timings":{"cache_n":0,"prompt_n":46,"prompt_ms":27.839,"prompt_per_token_ms":0.605195652173913,"prompt_per_second":1652.3582025216424,"predicted_n":4,"predicted_ms":11.083,"predicted_per_token_ms":3.6943333333333332,"predicted_per_second":270.68483262654513}}

data: [DONE]
```

- **A token's event is 254 or 255 bytes,** of which the token is one. The role's is 274, the finish reason's 245, and the usage's 571.
- **Every event is one `data:` line and a blank line,** with line feeds alone.

**A whole answer,** with `"max_tokens": 4`, as `application/json; charset=utf-8`, 630 bytes:

```json
{"choices":[{"finish_reason":"length","index":0,"message":{"role":"assistant","content":"\"Gra"}}],"created":1794319622,"model":"/models/stories260K.gguf","system_fingerprint":"b12242-3b4d6ab3f","object":"chat.completion","usage":{"completion_tokens":4,"prompt_tokens":46,"total_tokens":50,"prompt_tokens_details":{"cached_tokens":45}},"id":"chatcmpl-EwDZRIwwMXOg1OQBNb0HQZpNoScdmy5c","timings":{"cache_n":45,"prompt_n":1,"prompt_ms":0.383,"prompt_per_token_ms":0.383,"prompt_per_second":2610.9660574412533,"predicted_n":4,"predicted_ms":0.59,"predicted_per_token_ms":0.19666666666666666,"predicted_per_second":5084.745762711865}}
```

**Its errors:**

| Request | Answer |
|---|---|
| `"messages": "no"` | 400, `{"error":{"code":400,"message":"Expected 'messages' to be an array","type":"invalid_request_error"}}`, with `Connection: close` |
| `"temperature": "hot"`, with `"stream": true` | 400, the same shape, as plain JSON: no stream starts |
| `"fake_error": {"status": 503}`, a parameter it doesn't know | Ignored: the stream above was asked with it |

**From its code,** [`server-context.cpp`](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/server-context.cpp), read on 2026-11-10:
- **It waits for the first result before it answers.** An error before the first token is a plain HTTP error, "to match the OAI API behavior", and a stream's headers leave with its first token.
- **An error after that** is sent as `data: {"error": …}`, and the stream ends there.
- **A client that leaves** stops the generation: each wait checks whether the connection is closed.
- **A comment line, `:`,** may be sent as a ping, on a setting.

**From its README:** the reasoning comes in `reasoning_content`, "similar to Deepseek API". A reasoning chunk wasn't captured: this model doesn't reason. Plan step 2.3 captures one.

## Checked by the conformance suite

`docker compose run --rm conformance` now starts the fake server too, and checks it alone, as a backend's client would call it: 33 checks in [`test_fake_server.py`](../bench/conformance/test_fake_server.py) ([conformance](conformance.md#what-it-checks)). On 2026-11-10, on the Mac, all 321 checks passed, in 77.95 s. Its lines on the pace, with the host busy (a load average near 5):

```text
the machine's timers: 200 sleeps of 10 ms woke 2.02 ms late at the median, 7.13 ms at the p99; tolerance 17.13 ms (the p99 plus 10 ms)
fake-server: 42 tokens, lateness median 5.67 ms, min 3.34, max 18.87; the last quarter -0.72 ms on the first; headers at 114.8 ms
go-nethttp: 42 events, lateness median 6.29 ms, min 4.51, max 10.06; the last quarter +0.05 ms on the first; headers at 4.2 ms
```

- **The fake server keeps the pace as the Go backends' in-process fake does:** no token early, and no lateness that adds up.
- **Its headers came at 114.8 ms,** with the first token, due at 100 ms. A backend's come at once.

**In CI, on Linux's tighter timers,** the same day, in [run 42857893952](https://github.com/fkuhne/api-langs-bench/actions/runs/42857893952) on commit `7bf50e3`: 321 checks passed in 74.64 s.

```text
the machine's timers: 200 sleeps of 10 ms woke 0.11 ms late at the median, 0.12 ms at the p99; tolerance 10.12 ms (the p99 plus 10 ms)
fake-server: 42 tokens, lateness median 1.35 ms, min 0.76, max 1.82; the last quarter -0.06 ms on the first; headers at 101.3 ms
go-nethttp: 42 events, lateness median 1.43 ms, min 0.82, max 1.90; the last quarter -0.15 ms on the first; headers at 0.7 ms
```

There too, the fake server's tokens come as the Go backend's do: none early, 0.8 to 1.8 ms after their time, measured from when the request was sent.

## Measured alone, on 2026-11-10

R4 asks that no helper be the bottleneck. The fake server alone, under oha 1.16.0 from the runner's image, on Compose's network, with the backends stopped:
- **The machine:** the development Mac, an Apple M3 with 8 cores and 8 GB; Docker 29.5.2 in Colima's VM, with 4 CPUs and 5 GiB, which the load generator shares. The host was busy: a load average of 4 to 6.
- **The request:** a stream of 20 tokens, as a backend's client asks for one, with `"stream_options": {"include_usage": true}`. The first token at 50 ms, then one every 10 ms, so a stream is due to end at 240 ms: the `stream-20` workload's pace ([runner](runner.md)).
- **Each run:** 15 s at a fixed rate, with `--latency-correction`, after a 3 s warm-up. The server's CPU and memory were read once from `docker stats`, 8 s in.

| Rate | Connections | Sent, of those due | p50 | p99 | First byte, p50 | The server's CPU | Its memory |
|---|---|---|---|---|---|---|---|
| 1,000/s | 960 | 14,999 of 15,000 | 241.2 ms | 260.2 ms | 51.1 ms | 115% | 52 MiB |
| 2,000/s | 1,920 | 29,998 of 30,000 | 241.2 ms | 264.4 ms | 51.1 ms | 90% | 100 MiB |
| 4,000/s | 3,840 | 59,993 of 60,000 | 241.2 ms | 272.6 ms | 51.1 ms | 155% | 196 MiB |
| 6,000/s | 5,760 | 89,997 of 90,000 | 241.1 ms | 263.8 ms | 51.0 ms | 154% | 292 MiB |
| 8,000/s | 7,680 | 119,999 of 120,000 | 499.9, then 249.0 and 242.9 ms | 1,959.2, then 777.6 and 320.3 ms | 226.5, then 56.2 and 52.3 ms | 261%, then 222% and 214% | 398 to 408 MiB |
| 8,000/s | 2,048 | 119,991 of 120,000 | 241.3 ms | 261.5 ms | 51.0 ms | 162% | 143 MiB |
| 12,000/s | 4,096 | 179,992 of 180,000 | 243.5 ms | 342.8 ms | 52.7 ms | 218% | 259 MiB |
| 16,000/s | 4,096 | 221,967 of 240,000 | 711.8 ms | 1,437.1 ms | 75.3 ms | 241% | 271 MiB |

No request failed in any of these runs.

- **It kept 12,000 streams a second,** on 2.2 CPUs, with a p50 3.5 ms past the due time. That's three times what the Go backend kept under 1 CPU from its in-process fake, 4,000 ([runner](runner.md#what-the-ladder-rests-on)).
- **The connections cost more than the streams.** At 8,000 a second it was on time with 2,048 connections, and late in one run of three with 7,680, four times the streams open, as the runner sizes them. Each connection costs 50 to 70 kB, and this VM's 4 CPUs also run the load generator.
- **At 16,000 a second the run proves nothing:** 3,840 streams are open at once, and 4,096 connections leave no room.
- **So on this Mac, the helper's margin is thin above 6,000 a second.** The numbers that matter come from a machine with cores to spare for the load generator, the fake server and the backend. Plan step 3.1 sets those cores; plan step 2.4 checks each backend against it.

**The same request without a pace or a rate,** over 256 connections for 10 s, to see what the server costs without its timers:

| Answer | A second | p50 | The server's CPU | Its memory |
|---|---|---|---|---|
| A stream of 20 tokens | 34,958 | 3.0 ms | 237% | 18 MiB |
| A whole answer | 141,905 | 0.5 ms | 223% | 16 MiB |

**Beside the Go backend, under the same conditions,** at 8,000 a second for 15 s, with `net/http` serving its in-process fake without a CPU limit:

| Server | Connections | p50 | p99 | Its CPU |
|---|---|---|---|---|
| The fake server | 2,048 | 241.3 ms | 261.5 ms | 162% |
| `go-nethttp`, its in-process fake | 2,048 | 241.4 ms | 268.4 ms | 181% |
| `go-nethttp`, its in-process fake | 7,680 | 241.7 ms | 279.6 ms | 200% |

The fake server's chunks are about seven times the size of the backend's events, 238 bytes against 33 for a token of one character, for no more CPU.

Nothing was saved as a run: these check a helper, and aren't results.
