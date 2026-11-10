# 0023. The fake upstream server: Go, in its own module, shaped as llama.cpp's chunks, field for field

- Status: Accepted
- Date: 2026-11-10

## Context

Plan step 2.1 builds the fake upstream server: shaped like llama.cpp's OpenAI-compatible chat API, streaming the contract's tokens at the contract's pace, written once, and measured on its own to show it isn't the bottleneck ([0004](0004-three-local-upstreams-llama-cpp-a-fake-server-and-an-in-process-fake.md), R2 to R4). It lives in `fake-server/` ([0011](0011-lay-the-repository-out-by-role.md)). The contract leaves it two things: how it shapes its chunks, and how it shows each `fake_error` to the backend ([contract](../../contract/README.md#the-fakes)).

What was checked on 2026-11-10:

- **llama.cpp's real answers,** from its server, build `b12242-3b4d6ab3f`, with a 1.2 MB model, on the Mac ([fake server](../../docs/fake-server.md#what-llamacpp-sends)):
  - **A stream** is a chunk with the role and a null content, one chunk for each token, a chunk with the finish reason and an empty delta, a chunk with the usage and no choices when `stream_options.include_usage` asks for it, then `data: [DONE]`. Every chunk repeats `created`, `id`, `model`, `system_fingerprint` and `object`, and is about 250 bytes.
  - **A whole answer** has the same fields around a `message`, with `usage` and `timings`.
  - **A parameter it doesn't know,** such as `fake_error`, is ignored. A wrong type answers 400, with `{"error": {"code": 400, "message": …, "type": "invalid_request_error"}}`, even when a stream was asked for.
- **llama.cpp's code** (`server-context.cpp`, read that day):
  - it waits for the first result before it answers, so an error before the first token is a plain HTTP error, and the headers of a stream leave with the first token;
  - an error after that is a `data: {"error": …}` chunk, and the stream ends there;
  - a client that leaves stops the generation.
- **llama.cpp's README** puts the reasoning in `reasoning_content`.
- **ai-bootstrap's client** reads a chunk's `model`, `usage`, and its first choice's `finish_reason`, `delta.content` and `delta.reasoning_content`. It makes 429 of an upstream's 429, 503 of a status that means down, 502 of any other status, and 504 of a timeout alone ([its `services.py`](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/core/services.py)).
- **Go's capacity for this work:** without a limit, the Go backend on `net/http` served 8,000 of the `stream-20` streams a second from its in-process fake, on 1.6 CPUs, with a p50 of 245.0 ms against 240 ms due. Under 1 CPU it kept 4,000 ([runner](../../docs/runner.md#what-the-ladder-rests-on)). The Python backend answered 300 to 700 a second on one CPU ([runner](../../docs/runner.md#the-first-numbers-on-2026-11-10-on-a-core-i7-12850hx)).

## Decision

The fake server is written in Go, with the standard library alone, as its own module in `fake-server/`. It answers `POST /v1/chat/completions` with llama.cpp's chunks, field for field, and shows a `fake_error` the way llama.cpp shows a failure.

**Its language and place:**
- **Its own module,** `fake-server/`, with its own gates, the same as the Go backends' ([0013](0013-gates-equally-strict-for-every-language.md)). It shares no code with them: a change to a backend can't change the upstream it's measured against.
- **No limit on its CPUs or memory.** It's a helper, and must stay far from its ceiling.
- **It listens on port 8080,** as llama.cpp's server does, published on `127.0.0.1:8010`.

**Its answers:**
- **The chunks are llama.cpp's,** as captured: the same fields, in the same order. The captured stream and whole answer are kept as test fixtures, and a test compares the fake server's fields with them.
- **The values that vary in llama.cpp are fixed or counted here:**
  - `id` is `chatcmpl-` and 32 characters, from a counter;
  - `created` is the time;
  - `model` and `system_fingerprint` are `fake-server`;
  - `timings` is worked out from the fake's own timetable.
- **The reasoning** goes in `delta.reasoning_content`, one chunk for each token, and in `message.reasoning_content` in a whole answer.
- **The headers and the role chunk leave with the first token,** as llama.cpp's do. The finish chunk, the usage chunk and `[DONE]` leave with the last token.
- **The usage chunk** is sent only when `stream_options.include_usage` is true.
- **`GET /health`** answers `{"status":"ok"}`, as llama.cpp's.
- **The tokens, the length, the finish reason, the usage and the pace** are the contract's, from the same token file and the same `FAKE_*` settings. The start is when the request's body has been read.

**A `fake_error`:**

| `status` | Before the first token, or in a whole answer | After tokens, in a stream |
|---|---|---|
| 429 | HTTP 429, with `{"error": {"code": 429, …, "type": "rate_limit_error"}}` | `data: {"error": …}` with the same object, and the stream ends, without `[DONE]` |
| 502 | HTTP 400, with the type `invalid_request_error`: the upstream refuses the request | The same, with the code 400 |
| 503 | HTTP 503, with the type `unavailable_error`, as llama.cpp answers while it loads a model | The same, with the code 503 |
| 504 | No answer: the connection stays open and silent until the client leaves | No more chunks: the stream stays open and silent until the client leaves |

- **Each failure comes at the failing token's time,** as the contract says.
- **A malformed `fake_error`** answers HTTP 400 at once, with the type `invalid_request_error`.
- **Which answer becomes which of the contract's statuses** is the backends' mapping, plan step 2.2. The 504 needs an upstream timeout there, short enough for the conformance suite.

**A request it can't read,** such as a body that isn't JSON or `messages` that isn't a list, answers 400 with the type `invalid_request_error`, as llama.cpp does. Every other parameter is ignored.

**A client that leaves** stops its stream at once. The fake server logs one line for each stream closed early, with the tokens sent and the time since the start (R9).

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| Rust | The fastest, with no garbage collector. But a new toolchain and new gates now, before the Rust backend needs them |
| Python | The evaluation tool's language. But 300 to 700 streams a second on one CPU: it would be the bottleneck |
| Go, sharing the backends' fake package | Less code. But the upstream and two contestants would change together |
| The smallest OpenAI shape | Less to write. But chunks smaller than the real ones understate what a backend's client parses |
| Byte for byte, headers included | Nothing could tell them apart. But it means chasing every llama.cpp release, for bytes no client reads |
| Every `fake_error` status sent as itself | Simple, and no wait for the 504. But the backends' mapping would then differ from ai-bootstrap's, where 502 comes from a refusal and 504 from a timeout |
| A dropped connection for every failure | The simplest. But every failure would look the same to the backend |

## Consequences

- CI gains a sixth job, the fake server's gates, and its conformance job starts the fake server too ([0019](0019-ci-on-github-actions-five-jobs-on-x86-64-with-the-runners-own-docker.md)).
- The fake server is in a contestant's language. It isn't measured, it runs without limits, and backends reach it over HTTP alone; its own run shows how far its ceiling is.
- The contract's token rules now exist a fourth time: in Python, twice in Go, and in the evaluation tool. The conformance suite compares them through the backends once plan step 2.2 connects them.
- What isn't imitated, and may matter later:
  - llama.cpp's `Keep-Alive: timeout=5, max=100`, which closes a connection idle for 5 s or used 100 times. A backend's connection pool meets it only with the real server;
  - llama.cpp's slots, which serve a few requests at once. The fake server serves any number;
  - `/v1/models`, which the contract doesn't use.
- Plan step 2.3 checks the fixtures against the llama.cpp it pins, and captures a reasoning chunk.

## Assumptions to verify

- [x] The fake server keeps the contract's pace: no token early, none late beyond the machine's timers. To check in this step, with the conformance suite's pace rule. *2026-11-10, on the Mac: the rule passed in two runs out of two, with a median lateness of 8.74 and 5.67 ms against tolerances of 18.20 and 17.13 ms, beside 10.82 and 6.29 ms for `net/http`'s in-process fake ([fake server](../../docs/fake-server.md#checked-by-the-conformance-suite)). In CI, on Linux, its median lateness was 1.35 ms and its earliest token 0.76 ms late, beside 1.43 and 0.82 ms for `net/http`'s ([run 42857893952](https://github.com/fkuhne/api-langs-bench/actions/runs/42857893952)).*
- [x] It reaches a rate well above every backend's ceiling on the same machine: at least 8,000 `stream-20` streams a second on the Mac, twice what the Go backend kept under 1 CPU. To check in this step, alone, with oha. *2026-11-10: partly. It kept 12,000 a second over 4,096 connections, and 8,000 over 2,048. With connections at four times the streams open, as the runner sizes them, it kept 6,000, and was late at 8,000 in one run of three: the VM's 4 CPUs also run the load generator ([fake server](../../docs/fake-server.md#measured-alone-on-2026-11-10)).*
- [ ] On the machine that makes the numbers, the fake server stays far from its ceiling at every rate a backend is measured at. To check at plan step 2.4, and with plan step 3.1's cores.
- [ ] llama.cpp sends its role chunk and its first token in the same write. Unchecked: the capture shows them as separate events, not when each left.
- [x] llama.cpp's reasoning chunk is `{"reasoning_content": "…"}` in the delta, with no `content`. From its README; to capture at plan step 2.3. *2026-11-10: captured from Qwen3.5-0.8B: `"delta":{"reasoning_content":"Thinking"}` ([llama.cpp](../../docs/llama-cpp.md)).*
- [ ] A 429 never comes from llama.cpp itself. Unchecked; the fake server's 429 body follows its error format, with a type of our own.
- [ ] A backend's client can't tell the fake server from llama.cpp by anything it reads ([0004](0004-three-local-upstreams-llama-cpp-a-fake-server-and-an-in-process-fake.md)). To check at plan step 2.4, where each backend runs against both.

## Sources

- llama.cpp's server, image `ghcr.io/ggml-org/llama.cpp:server` at digest `sha256:4d2de15a0ffbce704777c64026b40512a71e0bbc0b303a5fe5ea9bf71760dff9`, 291.8 MB, with [`stories260K.gguf`](https://huggingface.co/ggml-org/models/blob/main/tinyllamas/stories260K.gguf): our run on the Mac, 2026-11-10.
- [llama.cpp's server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) and [`server-context.cpp`](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/server-context.cpp), read on 2026-11-10.
- ai-bootstrap's [`openai_compatible_client.py`](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/llm/openai_compatible_client.py), [`openai_errors.py`](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/llm/openai_errors.py) and [`services.py`](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/core/services.py), read on 2026-11-10.
- Our runs on 2026-11-09 and 2026-11-10 ([runner](../../docs/runner.md), [fake server](../../docs/fake-server.md)).
- The owner's picks, 2026-11-10.
