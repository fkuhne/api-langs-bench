# 0014. The Python backend: fresh from the contract, on uvicorn[standard] and FastAPI's SSE

- Status: Proposed
- Date: 2026-11-06

## Context

Plan step 1.3 builds the Python backend: FastAPI, as in ai-bootstrap ([product](../product.md#scope)), serving the contract ([0010](0010-the-contract-ai-bootstraps-chat-in-text-paced-fakes-and-openapi-3-2.md)) with its in-process fake. It must be written as a competent engineer would, following FastAPI's documented production set-up, and must not be tuned (R6).

What was read on 2026-11-06:
- **ai-bootstrap's code on chat's path is about 1,330 lines.** Much of it serves its module system, its users, multimodal input, `/api/llm/model`, and the OpenAI client, which step 2.2 needs. Its fake echoes the question. Ours is paced, reads the token file and fails on request, so it has to be written anew either way.
- **FastAPI's [deployment page](https://fastapi.tiangolo.com/deployment/manually/)** recommends Uvicorn, installed as `uvicorn[standard]`, which includes "`uvloop`, the high-performance drop-in replacement for `asyncio`, that provides the big concurrency performance boost". uvicorn 0.54.0's `standard` extra adds `uvloop`, `httptools`, `websockets`, `watchfiles`, `python-dotenv` and `pyyaml` (its PyPI metadata).
- **`fastapi[standard]`** adds much more, according to the 0.143.0 wheel's metadata: OpenTelemetry's SDK and exporter, Jinja2, `python-multipart`, `email-validator`, `fastapi-cli` and more.
- **FastAPI 0.143.0's `EventSourceResponse`** runs two extra tasks per stream, a producer and a keep-alive inserter. They connect through two memory streams, each holding one event. Each event is sent as soon as it's made. When the client leaves, the producer's task is cancelled once the response ends (`fastapi/routing.py`, lines 580-660).

## Decision

The Python backend is written fresh from the contract, taking the pieces of ai-bootstrap that fit as they are. It's served by `uvicorn[standard]`, and it streams through FastAPI's own `EventSourceResponse`.

- **From ai-bootstrap:**
  - the LLM port, cut to text: the client protocol and its answer and stream models;
  - the error classes, and their handler;
  - the chat router and its `error` event;
  - liveness and readiness.

  There's no module system, no users, and no `/api/llm/model`.
- **The pins** are ai-bootstrap's: FastAPI 0.143.0, uvicorn 0.54.0 with `[standard]`, pydantic-settings 2.15.0. The tests add httpx 0.28.1.
- **The fake** follows the contract: tokens from the file, deadlines on the event loop's clock, and `fake_error`. Its clock can be swapped, so the tests check its timing exactly.
- **The run:** one process, with uvicorn's defaults, its access log included. Workers, the access log and other run-time settings are step 3.1's fairness rule, the same for every backend.
- **FastAPI's served docs are off** (`/docs`, `/openapi.json`), since the contract drops them.
- **The service:** `python-fastapi` in Compose, published on `127.0.0.1:${PYTHON_FASTAPI_PORT:-8001}`.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| Copy ai-bootstrap's backend and cut it down | Leftovers of a template built for many modules, around one chat API. It would also differ in shape from the Go backend, which is written fresh anyway |
| Entirely fresh, ignoring ai-bootstrap | It throws away tested code, and readers of ai-bootstrap lose the link |
| Plain `uvicorn`, as ai-bootstrap | Not FastAPI's documented production install |
| `fastapi[standard]` | Packages a chat API never uses, in an image whose size we measure |
| A `StreamingResponse` writing the events' bytes | Less work per event, but not what FastAPI documents for SSE. That would be tuning (R6) |

## Consequences

- Python and Go line up file for file, which helps readers compare them.
- Step 2.2 can copy ai-bootstrap's OpenAI client into the same port.
- FastAPI's SSE machinery is part of Python's numbers, as it is for anyone using FastAPI.

## Assumptions to verify

- [ ] With `uvicorn[standard]` installed, uvicorn runs on uvloop and httptools in the container. To check from its start-up log in this step.
- [ ] A client that leaves mid-stream stops the fake within one token's gap. Checked by a test in this step; measured under load in step 3.3.

## Sources

- ai-bootstrap at [`edc0565`](https://github.com/fkuhne/ai-bootstrap/tree/edc0565), its backend's `app/`. Read on 2026-11-06.
- [FastAPI's deployment page](https://fastapi.tiangolo.com/deployment/manually/), read on 2026-11-06.
- uvicorn 0.54.0's metadata on PyPI, and FastAPI 0.143.0's wheel (`METADATA` and `fastapi/routing.py`), read on 2026-11-06.
- The owner's picks, 2026-11-06.
