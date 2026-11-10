# 0024. Each backend's upstream client: its plain HTTP client, one pool setting, no retries

- Status: Proposed
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

Each backend calls its upstream with its ecosystem's plain HTTP client, not an OpenAI SDK: httpx2 in Python, and `net/http` in Go. Every backend follows the same rules, written in [the contract](../../contract/README.md) with this step.

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

- [ ] Through the fake server, every backend passes the checks it passes from its in-process fake, the pace rule included. To check in this step.
- [ ] A stream longer than the timeout isn't cut, in either language, while its pieces keep coming. To check in this step.
- [ ] A client that leaves a backend closes the upstream's connection: the fake server logs it. To check in this step.
- [ ] 1,000 connections don't bind any backend at the rates measured. To check with plan step 2.4's runs.
- [ ] The idle expiry's defaults, 5 s in httpx2 and 90 s in Go, don't change a steady run. Unchecked; plan step 3.1.
- [ ] llama.cpp's real failures fit this mapping. To check at plan step 2.3.

## Sources

- PyPI's pages for `openai` 3.49.0, `httpx2` and `aiohttp`, read on 2026-11-10.
- [openai-python's `_constants.py`](https://github.com/openai/openai-python/blob/main/src/openai/_constants.py), read on 2026-11-10: its limits, timeout and retries.
- Our runs on 2026-11-10: `httpx2._config.DEFAULT_LIMITS` in the Python backend's checks image, and `http.DefaultTransport`'s fields under Go 1.27.3.
- ai-bootstrap's files named above, read on 2026-11-10.
- The owner's picks, 2026-11-10.
