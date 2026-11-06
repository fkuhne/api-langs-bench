# The contract

The one API every backend implements, and how both fakes behave. It's [ai-bootstrap](https://github.com/fkuhne/ai-bootstrap)'s stateless chat, cut to text ([0003](../spec/decisions/0003-every-backend-implements-ai-bootstraps-chat-api.md)). What was kept, and why, is in [0010](../spec/decisions/0010-the-contract-ai-bootstraps-chat-in-text-paced-fakes-and-openapi-3-2.md).

A change here changes every backend and the conformance suite in the same commit, and bumps `info.version` in [`openapi.yaml`](openapi.yaml).

## The files

- [`openapi.yaml`](openapi.yaml): the endpoints, the bodies and each event's data, in OpenAPI 3.2.
- **This page:** what no schema says: the events' order, sending each one at once, a client that leaves, the fakes, and how answers are compared.
- [`redocly.yaml`](redocly.yaml): the lint's rules: Redocly's recommended set, except the rule that wants a 4xx answer on every endpoint, which the health endpoints don't have ([0013](../spec/decisions/0013-gates-equally-strict-for-every-language.md)).
- [`fake-tokens.json`](fake-tokens.json): the 175 tokens both fakes answer with. They hold quotes, `<`, `&`, backslashes, accents, three scripts and an emoji, so each language's JSON encoder does real work.

## The endpoints

| Endpoint | What it does |
|---|---|
| `GET /api/health` | Liveness: `{"status": "ok"}` while the process is up. It checks nothing else |
| `GET /api/health/ready` | Readiness: `{"status": "ok", "checks": {"llm": "ok"}}`, or 503 with `unavailable` while the upstream is. The in-process fake is always ready |
| `POST /api/chat` | The whole answer |
| `POST /api/chat/stream` | The answer as server-sent events |

## The request

Both chat endpoints take the same JSON body, sent with `Content-Type: application/json`:

```json
{"messages": [{"role": "user", "content": "In one sentence, what is an LLM?"}], "parameters": {"max_tokens": 5}}
```

- **`messages`:** one or more. Each has a `role`: `system`, `user` or `assistant`. Each has a `content`: a non-empty string.
- **`parameters`:** optional, any JSON object. The backend passes it to the upstream unchanged, and doesn't read it.
  - **Reserved keys:** `model`, `messages`, `stream` and `stream_options`. The backend sets them itself, so a request that sends one is invalid.
  - **What the fakes read:** `max_tokens` and `fake_error` ([The fakes](#the-fakes)).
- **Other fields** of the body are ignored.
- **An invalid body** answers 422 with a JSON object that has a `detail`. What `detail` holds is each framework's own; FastAPI's is a list of errors. It's never compared.

## The whole answer

`POST /api/chat` answers 200 with:

```json
{"content": "A backend in front of", "reasoning": null, "model": "fake", "finish_reason": "length",
 "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}}
```

`reasoning` holds the model's reasoning when it shows any. `finish_reason` and `usage` are what the upstream reported, or null.

## The stream

`POST /api/chat/stream` answers 200 once the body is valid. The headers are `Content-Type: text/event-stream` (a `charset` may follow) and `Cache-Control: no-cache`.

**The wire format.** Each event is an `event:` line, one `data:` line holding JSON, and a blank line. Lines end with `\n`. No event has an `id:` or a `retry:`. For the request above, from the in-process fake:

```text
event: token
data: {"text":"A"}

event: token
data: {"text":" backend"}

event: token
data: {"text":" in"}

event: token
data: {"text":" front"}

event: token
data: {"text":" of"}

event: done
data: {"model":"fake","finish_reason":"length","usage":{"prompt_tokens":7,"completion_tokens":5,"total_tokens":12}}

```

**The events:**

| Event | Data | When |
|---|---|---|
| `reasoning` | `{"text": "…"}` | The next piece of the model's reasoning |
| `token` | `{"text": "…"}` | The next piece of the answer |
| `done` | `{"model", "finish_reason", "usage"}` | The answer is complete |
| `error` | `{"status", "detail"}` | The upstream failed |

**The rules:**
- **The order:** any `reasoning` events, then any `token` events, then exactly one `done` or `error`, then the stream closes.
- **One event per piece.** Each piece of text the upstream sends becomes one event. A backend never merges pieces or splits them. A chunk with no text, such as an OpenAI-compatible stream's first chunk, which carries only the role, sends nothing.
- **Each event is sent as soon as it's made,** never held back to be sent with the next. How quickly is what the benchmark measures (R9).
- **Comments are allowed** anywhere, and clients ignore them. FastAPI sends `: ping` after 15 seconds without an event.
- **An upstream's failure,** even before the first token, ends the stream with an `error` event. Its `status` is the one the same request gets from `POST /api/chat`: 429, 502, 503 or 504. No `done` follows it.
- **A client that leaves** stops the work. When the client closes the connection, the backend stops reading its upstream and closes its connection to it. The in-process fake stops making tokens. How fast that happens is measured (R9, plan step 3.3), not bounded here.

## Errors

| Status | When | Body |
|---|---|---|
| 422 | The body isn't a valid chat request | `{"detail": …}`, each framework's own |
| 429 | The upstream is rate-limiting requests | `{"detail": "…"}` |
| 502 | The upstream refused the request | `{"detail": "…"}` |
| 503 | The upstream can't be reached, or is down | `{"detail": "…"}` |
| 504 | The upstream didn't answer in time | `{"detail": "…"}` |

These are ai-bootstrap's ([foundations](https://github.com/fkuhne/ai-bootstrap/blob/main/docs/foundations.md#errors)). Which of an upstream's own answers becomes which status is plan step 2.2. A stream answers only 422 itself; every other failure becomes an `error` event.

## Settings

Environment variables, read at start-up. A backend refuses to start with an invalid value.

| Variable | Default | What it sets |
|---|---|---|
| `LLM_PROVIDER` | `fake` | `fake` for the in-process fake. `openai-compatible` for an upstream, whose settings arrive in plan step 2.2. The names are ai-bootstrap's, but its default is `openai-compatible` |
| `FAKE_ANSWER_TOKENS` | `256` | The answer's length when `max_tokens` doesn't cut it. A whole number, 1 or more |
| `FAKE_REASONING_TOKENS` | `0` | Reasoning tokens before the answer. A whole number, 0 or more |
| `FAKE_FIRST_TOKEN_MS` | `0` | Milliseconds from the start to the first token. A whole number, 0 or more |
| `FAKE_TOKEN_GAP_MS` | `0` | Milliseconds between one token and the next. A whole number, 0 or more |

With the defaults, the fakes answer as fast as they can. The workloads set the pace (plan step 3.2).

## The fakes

Both fakes behave the same, token for token and on the same timetable ([0004](../spec/decisions/0004-three-local-upstreams-llama-cpp-a-fake-server-and-an-in-process-fake.md), R3):
- **the in-process fake,** selected by `LLM_PROVIDER=fake`;
- **the fake server** of plan step 2.1, which reads the same `FAKE_*` settings.

How the fake server shapes its chunks, and how it shows each failure to the backend, is step 2.1's.

### The answer

- **The tokens:** both the reasoning and the answer take tokens from [`fake-tokens.json`](fake-tokens.json), in order, each starting from the first. After the last token they wrap around to the first. The file ends with a paragraph break, so the text reads on.
- **The reasoning:** `FAKE_REASONING_TOKENS` tokens, sent as `reasoning` events.
- **The answer's length** is `FAKE_ANSWER_TOKENS`, unless `max_tokens` is set to a smaller positive whole number, such as `5`. The fakes ignore any other value of `max_tokens`. It doesn't count the reasoning.
- **The finish reason** is `length` when `max_tokens` cut the answer short, and `stop` otherwise.
- **The model** is `fake` for the in-process fake.
- **The usage:**
  - `completion_tokens` counts the reasoning and the answer;
  - `prompt_tokens` counts the words in all the messages' contents. Words are separated by runs of spaces, tabs, line feeds and carriage returns. Any other character, a non-breaking space included, belongs to a word;
  - `total_tokens` is the sum of the two.

### The pace

Counting the reasoning and the answer together, token *i* (from 0) is due at:

> start + `FAKE_FIRST_TOKEN_MS` + *i* × `FAKE_TOKEN_GAP_MS`

- **The start** is when the in-process fake is called, once the body is valid. For the fake server, it's when its request has arrived.
- **The fake waits until each token's time,** rather than sleeping a gap after each token, so delays don't add up. A token whose time has passed goes at once.
- **The whole answer** comes at the last token's time.

How close to its time each token must be is set by the conformance suite (plan step 1.5).

### Errors on request

A `fake_error` parameter makes the fake fail, so the conformance suite can cause each error:

```json
{"messages": [{"role": "user", "content": "Hi"}], "parameters": {"fake_error": {"status": 503, "after_tokens": 2}}}
```

- **`status`** is 429, 502, 503 or 504. The failure is the upstream error that status stands for, raised the way the backend's real upstream client raises it.
- **`after_tokens`** is a whole number, 0 or more, and 0 by default. The fake makes that many tokens at its pace, or all of them if the answer is shorter.
- **The failure takes the place of the next token,** at that token's time. A stream sends the tokens made, then an `error` event. The whole answer gets the status instead.
- **A malformed `fake_error`,** such as an unknown status, makes the fake fail at once with 502, the way an upstream refuses a parameter it doesn't accept.

The backend passes `fake_error` on like any other parameter, so the fake server obeys it too.

## Comparing answers

The conformance suite (plan step 1.5) compares each backend's answers to the contract by these rules:
- **Statuses and event names** must match exactly.
- **JSON is compared after parsing.** Key order, white space and how characters are escaped don't count; Go writes `<` as `<` by default (from memory, unchecked). A field that is null may be left out.
- **Token texts** must match exactly, event by event.
- **A `detail`** is never compared, only its presence.

## Not in the contract

- **Conversations,** which arrive in Phase 5 ([0005](../spec/decisions/0005-conversations-on-postgresql-as-version-1s-last-backend-phase.md)), and the user they need (`X-User-Id`).
- **ai-bootstrap's other endpoints:** `/api/llm/model`, `/api/modules`, and the served docs.
- **Images, audio and video** in messages.
- **Ports, containers and limits:** plan steps 1.2 and 3.1.
- **The upstream's settings and error mapping:** plan step 2.2.
