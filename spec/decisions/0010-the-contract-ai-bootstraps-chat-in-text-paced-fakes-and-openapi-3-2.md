# 0010. The contract: ai-bootstrap's chat in text, paced fakes, and OpenAPI 3.2

- Status: Proposed
- Date: 2026-11-06

## Context

Every backend implements one contract, taken from ai-bootstrap's chat ([0003](0003-every-backend-implements-ai-bootstraps-chat-api.md)). Both fakes behave the same, and the contract says how ([0004](0004-three-local-upstreams-llama-cpp-a-fake-server-and-an-in-process-fake.md), R3). Plan step 1.1 left three choices: what of ai-bootstrap's API to keep, how the fakes behave, and the contract's form.

What ai-bootstrap does, read in its public repository at `edc0565` on 2026-11-06. The chat files there match the owner's local copy, file for file:
- **Endpoints:** `POST /api/chat` and `POST /api/chat/stream`, plus `GET /api/health` (liveness), `GET /api/health/ready` (readiness), `GET /api/llm/model`, `GET /api/modules`, and the docs at `/api/docs`.
- **The body:** `messages`, each with a role and a content that is text or a list of parts (images, audio, video). `parameters` holds any JSON, except four keys the backend sets itself: `model`, `messages`, `stream` and `stream_options`.
- **The stream:** once the body is valid, the answer is 200. Any upstream failure, even before the first token, ends the stream with an `error` event ([router.py:40-45](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/modules/chat/router.py#L40-L45)).
- **The fake** echoes "Fake answer to: <question>", one word per token, with no pacing. `max_tokens` cuts it, counted in words ([fake_llm_client.py](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/llm/fake_llm_client.py)).

What FastAPI 0.143.0 does, read in its wheel on 2026-11-06 (`fastapi/sse.py`, `routing.py`, `exception_handlers.py`):
- **Each event is written as an `event:` line and a `data:` line,** followed by a blank line. The data is the model's compact JSON, with nulls included.
- **After 15 seconds with no event,** it sends the comment `: ping`.
- **It sets two headers:** `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
- **Its 422 body is** `{"detail": [{loc, msg, type, …}]}`.
- **The OpenAPI it generates is version 3.1.0.**

OpenAPI 3.2.0 (September 2025) can describe a `text/event-stream`, read in the specification on 2026-11-06 (§4.14.4, and the example "Server-Sent Event Streams"):
- **`itemSchema` describes one event.**
- **`oneOf` switches on the event's name.**
- **`contentMediaType` and `contentSchema` describe the JSON inside `data`.**

OpenAPI 3.1 can't describe the events at all.

## Decision

The contract is ai-bootstrap's stateless chat, cut to text. Both fakes make a fixed answer from one committed token file, at a pace set by settings. It's written by hand as an OpenAPI 3.2 file and a page, in a root `contract/` folder.

**What we keep of ai-bootstrap's API:**
- **Chat:** `POST /api/chat` and `POST /api/chat/stream`.
- **Health:** `GET /api/health` and `GET /api/health/ready`. Liveness also gives a bare-HTTP number for each language.
- **`reasoning` events.** The fakes send them only when a setting asks.
- **Free `parameters`,** with the four reserved keys. The backend passes them to the upstream unchanged, and every workload sends the same ones.
- **We drop** `/api/llm/model`, `/api/modules` and the served docs.
- **Message content is a non-empty string.** Parts are dropped, since the project is text only.

**The fakes** (the in-process fake, and the fake server of step 2.1):
- **The tokens:** the answer's tokens come from `contract/fake-tokens.json`, in order, and wrap around at the end.
- **The answer's length** is `max_tokens` when the request sets it, up to the setting `FAKE_ANSWER_TOKENS`. The finish reason is `length` when `max_tokens` cut the answer, and `stop` otherwise.
- **Reasoning:** `FAKE_REASONING_TOKENS` reasoning tokens come before the answer. The default is none.
- **The pace:** `FAKE_FIRST_TOKEN_MS` and `FAKE_TOKEN_GAP_MS`. Token *i* is due at `start + first + i × gap`. The fake waits for that time instead of sleeping a gap after each token, so delays don't add up.
- **The whole answer** comes when its last token would have.
- **Errors on request:** a `fake_error` parameter, such as `{"status": 503, "after_tokens": 2}`, makes the fake fail after that many tokens. The backend passes it through like any other parameter, so the fake server obeys it too.

**The form:**
- **`contract/openapi.yaml`:** OpenAPI 3.2, written by hand. It describes the endpoints, the bodies, and each event's data.
- **`contract/README.md`:** what no schema can say: the events' order, flushing, a client that leaves, the fakes, and how answers are compared.
- **`contract/fake-tokens.json`:** the tokens.
- **The folder is at the root,** because code reads it: the fakes, and the conformance suite.
- **If 3.2 won't lint** when the gates arrive (step 1.2), the file falls back to 3.1, and the events live only in the page.

**Smaller rules:**
- **JSON is compared after parsing.** Key order and white space don't count, and a null field may be left out.
- **Validation errors** answer 422, with a JSON body that has a `detail`. Its content is each framework's own.
- **The stream's order:** any `reasoning` events, then `token` events, then exactly one `done` or `error`. Comments are allowed. Each event is sent as soon as it's made.
- **A client that leaves:** the backend stops reading the upstream and closes its connection to it.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| Drop the `reasoning` events | Thinking models on llama.cpp and Ollama send them, under `reasoning_content` or `reasoning`. Reading them is real backend work |
| A fixed, typed set of parameters | Easier in Go, but it's not ai-bootstrap's API. Passing free JSON on is real work, and harder in a static language: worth measuring |
| Keep content parts, text only | A union type in every language, and nothing measured needs it |
| The fakes echo the question, as in ai-bootstrap | The answer's length would depend on the question, and every language would have to split words the same way |
| The pace set per request as well | Benchmark knobs inside the API's parameters, and more to keep identical |
| One prose page | Nothing a tool can check |
| OpenAPI 3.1 by hand, plus a page | 3.1 can't describe the events. It stays the fallback |
| JSON Schema files, plus a page | No machine-readable list of endpoints |
| OpenAPI generated from the Python backend | One language would become the reference |

## Consequences

- Each language reads the token file and the `FAKE_*` settings, and keeps a deadline-based timer. The conformance suite (step 1.5) checks both.
- The conformance suite can make each error happen, with `fake_error`, against any fake.
- Go has to pass free JSON on to its upstream (step 2.2).
- A change to `contract/` changes every backend and the conformance suite in the same commit (AGENTS.md).
- The gates of step 1.2 lint `contract/openapi.yaml`.

## Assumptions to verify

- [ ] A linter accepts OpenAPI 3.2. Redocly CLI says it does, on weak sources. To check in step 1.2.
- [ ] Each language's documented production set-up can send an event at once, without buffering it: uvicorn for Python, `net/http`'s flushing for Go. To check in steps 1.3 to 1.5.
- [ ] Each framework learns that a streaming client has left, and stops the work. For example, the generator is cancelled in FastAPI, and the request's context in Go. Unchecked; measured in step 3.3.
- [ ] Go's OpenAI SDK can pass free parameters through unchanged. Unchecked; step 2.2.
- [ ] Go's `encoding/json` escapes `<`, `>` and `&` by default, and comparing parsed JSON absorbs it. From memory, unchecked.

## Sources

- ai-bootstrap at [`edc0565`](https://github.com/fkuhne/ai-bootstrap/tree/edc0565): [chat's router](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/modules/chat/router.py), [the LLM port](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/llm/llm_client.py), [the fake](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/llm/fake_llm_client.py), [the errors](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/core/errors.py), [health](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/health/router.py) and [the LLM settings](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/llm/config.py). Read on 2026-11-06.
- FastAPI 0.143.0's wheel from PyPI: `fastapi/sse.py`, `fastapi/routing.py`, `fastapi/exception_handlers.py` and `fastapi/applications.py`. Read on 2026-11-06.
- [The OpenAPI 3.2.0 specification](https://spec.openapis.org/oas/v3.2.0.html), §4.14.4, "Special Considerations for Server-Sent Events", and the example "Server-Sent Event Streams". Read on 2026-11-06.
- On Redocly CLI and OpenAPI 3.2: [OpenApi.tools](https://openapi.tools/tools/redocly-cli/), and [a mirror of its README](https://awesome.ecosyste.ms/projects/github.com%2Fredocly%2Fredocly-cli). Read on 2026-11-06.
- The owner's picks, 2026-11-06.
