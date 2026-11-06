# 0003. Every backend implements ai-bootstrap's chat API

- Status: Proposed
- Date: 2026-11-06

## Context

Comparing languages needs every backend to do the same work. The owner's [ai-bootstrap](https://github.com/fkuhne/ai-bootstrap) already defines and runs an AI backend's chat API, and the owner asked to follow it (2026-11-06). Its foundations page describes it, as read on 2026-11-05:
- **[Chat](https://github.com/fkuhne/ai-bootstrap/blob/main/docs/foundations.md#chat-whole-or-streamed):** `POST /api/chat` returns the whole answer. `POST /api/chat/stream` sends server-sent events: `reasoning` and `token` pieces, then `done` with the model, the finish reason and the usage, or `error` with the status the same request gets unstreamed. Both are stateless. The body is `{"messages": [...], "parameters": {...}}`.
- **[Errors](https://github.com/fkuhne/ai-bootstrap/blob/main/docs/foundations.md#errors):** an upstream's failure becomes 502 (refused), 503 (unreachable or down), 504 (timeout) or 429 (rate-limited).
- **[The LLM port](https://github.com/fkuhne/ai-bootstrap/blob/main/docs/foundations.md#the-llm-port):** an OpenAI-compatible client with retries, and a fake (`LLM_PROVIDER=fake`).

The owner's focus is the backend for AI: chat, streaming and their metrics. Login isn't a concern, and messages are text only for now.

## Decision

Every backend implements one contract, taken from ai-bootstrap's chat: the two endpoints, the body, the stream's events, the readiness check and the errors. Stateless, and text only. Conversations come later, in version 1's last backend phase ([0005](0005-conversations-on-postgresql-as-version-1s-last-backend-phase.md)).

The contract is written down once, in this repository. Every backend is checked against it by one conformance suite. What to keep of ai-bootstrap's API, such as the `reasoning` events and the free `parameters`, is plan step 1.1.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| OpenAI's chat completions shape, the backend as a pure proxy | The backend would pass the provider's chunks through untouched. That measures less of each language, and isn't what an app's backend does: ai-bootstrap reads the chunks once and sends its own events. |
| A new API designed for this benchmark | More work, and no real app behind it. |
| Conversations from the start | The owner asked for stateless chat first; conversations follow once it's measured ([0005](0005-conversations-on-postgresql-as-version-1s-last-backend-phase.md)). |

## Consequences

- The Python backend can start from ai-bootstrap's code (step 1.3).
- Readers who know ai-bootstrap see the same API.
- A change to the contract changes every backend and the conformance suite in the same commit.

## Assumptions to verify

- [ ] The contract can be written precisely enough that every backend's events match, field for field.
- [ ] ai-bootstrap's free `parameters` don't make the backends do different work. If they do, the contract fixes them.

## Sources

- ai-bootstrap's [`docs/foundations.md`](https://github.com/fkuhne/ai-bootstrap/blob/main/docs/foundations.md), read on 2026-11-05.
- The interview, 2026-11-05 and 2026-11-06.
