# 0024. Each backend's upstream client: its plain HTTP client, one pool setting, no retries

- Status: Accepted
- Date: 2026-11-10

## Context

Plan step 2.2 gives each backend its upstream client: the code that calls an OpenAI-compatible chat API, whole and streamed, and turns its failures into the contract's errors (R2). Until now a backend answered only from the fake inside it. The first upstream to call is the fake server ([0023](0023-the-fake-upstream-server-go-in-its-own-module-shaped-as-llama-cpps-chunks.md)); llama.cpp follows in plan step 2.3.

ai-bootstrap, whose chat the contract is cut from, calls its upstream through the OpenAI SDK. What was read and run on 2026-11-10:

- **The OpenAI SDK for Python, 3.49.0, runs on httpx2** (PyPI). ai-bootstrap turns the SDK's own retries off, and retries by its own rule: twice by default, on a connection error, a 429 or a 5xx, until the stream opens ([its client](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/llm/openai_compatible_client.py)).
- **Its settings** are `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS` (300) and `LLM_MAX_RETRIES` (2) ([its `config.py`](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/llm/config.py)).
- **Its error mapping:** a 429 stays 429; 502, 503, 504 and 529 mean the upstream is down, and become 503; any other status is a refusal, 502; a timeout is 504; a connection error is 503 ([its `services.py`](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/core/services.py), [`openai_errors.py`](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/llm/openai_errors.py)). An error sent inside a stream reaches it as the SDK's plain `APIError`, and becomes one generic 502.
- **Its readiness** is a completion of one token, with a 5 s timeout. A 400 counts as ready.
- **Each client's default connection pool,** read from the libraries:

  | Client | At most | Kept idle |
  |---|---|---|
  | httpx2 2.13.1 | 100 connections | 20, for 5 s |
  | The OpenAI SDK, on httpx2 | 1,000 | 100 |
  | Go 1.27.3's `net/http` | No maximum | 2 for each host, for 90 s |

  With 100 connections, a backend can hold 100 streams open: about 416 a second of the `stream-20` workload, whose streams last 240 ms (computed).
- **A timeout means different things by default.** httpx2's is for each wait: to connect, to send, and for each read. Go's `http.Client.Timeout` covers the whole exchange, body included, so it would cut a long stream.

## Decision

Each backend calls its upstream with its ecosystem's plain HTTP client, not an OpenAI SDK: httpx2 in Python, and `net/http` in Go. Every backend follows the same rules, written in [the contract](../../contract/README.md#the-upstream).

- **Why not the SDK.** A backend then shows every line of the call, and the comparison is between HTTP clients, not between SDKs of uneven quality. Later languages don't all have an official SDK.
- **Python uses httpx2,** the client the OpenAI SDK itself runs on, already pinned here.
- **The settings are ai-bootstrap's,** less the retries, plus the pool:

  | Setting | Default | What |
  |---|---|---|
  | `LLM_PROVIDER` | `fake` | `openai-compatible` selects the upstream client |
  | `LLM_BASE_URL` | `http://fake-server:8080/v1` | Where the upstream's API is |
  | `LLM_MODEL` | `local` | The model asked for |
  | `LLM_API_KEY` | `local` | Sent as a bearer token |
  | `LLM_TIMEOUT_SECONDS` | `300` | How long the backend waits while nothing arrives |
  | `LLM_MAX_CONNECTIONS` | `1000` | The connection pool's size |

- **One pool setting, the same for every backend.** A backend opens at most `LLM_MAX_CONNECTIONS` connections to its upstream, and keeps as many idle. The default is the OpenAI SDK's own maximum. It's provisional until plan step 3.1. How long an idle connection is kept stays each library's default.
- **One meaning for the timeout.** It bounds each wait in which nothing arrives from the upstream: for a connection, for the answer to start, and between two pieces of its body. It doesn't bound the whole answer.
- **No retries.** A request reaches the upstream once. Retries would hide failures and add load nobody asked for, and behaviour under failure is out of version 1's scope ([product](../product.md#scope)).
- **The error mapping is ai-bootstrap's,** for an HTTP status, a timeout and a connection error.
- **An error inside a stream is mapped by its code,** by the same rule as an HTTP status: 429, a status that means down, or a refusal. Without a code it's a 502.
- **Readiness is ai-bootstrap's:** a completion of one token, with a timeout of 5 s, or the setting's if shorter. A 400 counts as ready.
- **A client that leaves** closes the upstream's connection at once.
- **The conformance suite runs every backend twice:** from its in-process fake, and through the fake server, whose answers must match except for the model's name.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| Each ecosystem's OpenAI SDK | As ai-bootstrap. But the SDKs differ in quality and in what they hide, and the owner picked the plain client |
| aiohttp for Python | Reputed faster (unchecked). But a second HTTP stack beside httpx2, and further from what the SDK runs on |
| Each library's default pool | Nothing to configure. But httpx2's 100 connections would cap Python near 416 streams a second, and the run would measure a default |
| ai-bootstrap's retries, off by default | The code would exist for later. But it's more to write and check in every language, unused |
| One generic error for a failure inside a stream | As ai-bootstrap. But every late failure would look the same, and the suite couldn't tell them apart |
| Readiness from the upstream's `/health` | Cheaper. But only llama.cpp has it: Ollama Cloud doesn't |

## Consequences

- Each language writes its own reader of the upstream's stream, by hand. That's code to keep alike, held by the conformance suite.
- The suite takes about twice as long, and each 504 check waits for the timeout, set to 1 s there.
- A readiness check costs the upstream one request of one token.
- Plan step 3.1 decides the pool's real size and the idle expiry, with the other fairness rules.
- The backends can call llama.cpp (plan step 2.3) and Ollama Cloud (plan step 4.2) with the same client.

## Assumptions to verify

- [x] Through the fake server, every backend passes the checks it passes from its in-process fake, the pace rule included. To check in this step. *2026-11-10, on the Mac: yes for the answers, 627 checks passed. The pace rule needed 5 ms more behind the fake server: Python's stream came 17.75 ms late at the median against a tolerance of 15.34 ms ([conformance](../../docs/conformance.md#through-the-fake-server-on-2026-11-10)). In CI, on Linux, it passed three times out of three, with a median lateness through the fake server of 3.2 to 3.4 ms for Python and 1.9 to 2.0 ms for Go ([run 42905293392](https://github.com/fkuhne/api-langs-bench/actions/runs/42905293392)).*
- [x] A stream longer than the timeout isn't cut, in either language, while its pieces keep coming. To check in this step. *2026-11-10: a stream 1.54 s long ended with `done` under a 1 s timeout, from all three backends ([backends](../../docs/backends.md#the-upstream-client)). The suite's paced stream, 920 ms long under the same timeout, passes too.*
- [x] A client that leaves a backend closes the upstream's connection: the fake server logs it. To check in this step. *2026-11-10: a client that left at 120 ms was logged by the fake server at 114.6, 118.4 and 131.8 ms from its own start, for Python, `net/http` and Gin ([backends](../../docs/backends.md#the-upstream-client)). Once each, by hand: the suite doesn't check it yet.*
- [ ] 1,000 connections don't bind any backend at the rates measured. To check with plan step 2.4's runs.
- [ ] The idle expiry's defaults, 5 s in httpx2 and 90 s in Go, don't change a steady run. Unchecked; plan step 3.1.
- [x] llama.cpp's real failures fit this mapping. To check at plan step 2.3. *2026-11-10: partly. A refused parameter got llama.cpp's 400 and the backends' 502, and a stopped llama.cpp a 503 ([llama.cpp](../../docs/llama-cpp.md)). Its 503 while a model loads wasn't seen: the healthcheck holds the backends back until it's loaded.*

## Learned while building it

- **The pace rule's tolerance is 5 ms wider behind the fake server.** An event there crosses one more late wake-up, which on the Mac's VM is worth several milliseconds. This amends [0017](0017-the-conformance-suite-pytest-that-drives-compose-and-a-pace-rule-from-the-machines-timers.md)'s rule for that case alone.
- **Go's `http.Client.Timeout` couldn't be used:** it bounds the whole answer. The Go client keeps a timer of its own, started again each time something arrives.
- **Closing a body isn't enough to leave in Go:** its client reads on for up to 50 ms. The Go client ends the request's context first.
- **Calling an upstream costs a backend much of its CPU.** In a sketch on the Mac, under 1 CPU, Python ran out between 300 and 500 streams a second through the fake server, and both Go servers were at 95% and 98% of their CPU at 2,000, against 500 and 4,000 from their in-process fakes ([backends](../../docs/backends.md#the-upstream-client)). Plan step 2.4 measures it.
- **The contract's version is 1.1.0,** with the upstream's rules.

## Sources

- PyPI's pages for `openai` 3.49.0, `httpx2` and `aiohttp`, read on 2026-11-10.
- [openai-python's `_constants.py`](https://github.com/openai/openai-python/blob/main/src/openai/_constants.py), read on 2026-11-10: its limits, timeout and retries.
- Our runs on 2026-11-10: `httpx2._config.DEFAULT_LIMITS` in the Python backend's checks image, and `http.DefaultTransport`'s fields under Go 1.27.3.
- ai-bootstrap's files named above, read on 2026-11-10.
- Our runs on 2026-11-10 ([backends](../../docs/backends.md#the-upstream-client), [conformance](../../docs/conformance.md#through-the-fake-server-on-2026-11-10)).
- The owner's picks, 2026-11-10.
