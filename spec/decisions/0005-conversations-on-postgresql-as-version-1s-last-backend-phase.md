# 0005. Conversations on PostgreSQL, as version 1's last backend phase

- Status: Proposed
- Date: 2026-11-06

## Context

The owner first asked for stateless chat only, then asked whether a database would serve the benchmark (2026-11-06). An AI app's backend usually stores its conversations, as ai-bootstrap's [conversations module](https://github.com/fkuhne/ai-bootstrap/blob/main/docs/foundations.md#conversations) does. It reads the history before calling the model, and stores the question and the answer together once the answer is complete.

What a database adds that stateless chat can't show:
- the time the history's read adds before the first token;
- the time storing the turn adds after the stream;
- what happens when streams outnumber the database's connections. A backend that holds its connection while it streams runs out of them, and its tail latency jumps. That depends on the framework and on how the code is written;
- a plain database read, listing conversations, as a baseline readers know from general web benchmarks;
- for the "learn" goal, each ecosystem's drivers, connection pools and queries.

What it costs: a store in every language, PostgreSQL shared by every run, and state that must be reset between runs.

## Decision

Version 1's last backend phase adds ai-bootstrap's conversations, in text, on PostgreSQL. It comes after stateless chat is measured from end to end, and before any new language, so that each new language implements the whole API once.
- **One schema,** in plain SQL migrations, shared by every backend. Each backend writes its own queries, with its ecosystem's driver.
- **PostgreSQL is measured on its own first,** to show it isn't the bottleneck.
- **Each run starts from the same state,** reset and seeded.
- **The user** comes from `X-User-Id`, as in ai-bootstrap. There's no login.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| No database | It misses what an AI app's backend does around the call. That was the owner's first call, changed on 2026-11-06. |
| The first item of "Next" | It keeps version 1 smaller, but the first report would cover only proxying, which is less useful to a tech lead. |
| Each backend's own migrations, through its ORM | The schemas could drift apart, and the backends would no longer do the same work. |

## Consequences

- Phase 5 of the plan.
- The database's numbers show only against the fakes. Against llama.cpp, a few milliseconds disappear in the model's seconds.

## Assumptions to verify

- [ ] Database time is visible against the fakes.
- [ ] PostgreSQL, sized for the run, isn't the bottleneck.

## Sources

- ai-bootstrap's [conversations](https://github.com/fkuhne/ai-bootstrap/blob/main/docs/foundations.md#conversations), read on 2026-11-05.
- The interview, 2026-11-06.
