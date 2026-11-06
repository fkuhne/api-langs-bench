# 0004. Three local upstreams: llama.cpp, a fake server and an in-process fake

- Status: Proposed
- Date: 2026-11-06

## Context

The owner wants the backends to give real service, with llama.cpp behind them "so that we can see things happening". The owner also wants a flag that makes a backend use a fake LLM, bypassing the upstream (2026-11-06).

A real model's reply takes seconds on a CPU, and llama.cpp's server serves only a few requests at once. A backend's own cost is micro- to milliseconds. Measured against a real model alone, the languages' differences disappear. LLM gateway benchmarks measure their overhead against a mock upstream for this reason: Bifrost's used a mock OpenAI response with 60 ms of latency ([notes](../../docs/benchmarking.md#prior-art)).

## Decision

Each backend reaches its upstream by a setting, the same for every backend:
- **llama.cpp's server,** pinned, with one small model on CPU. It's the real thing.
- **A fake upstream server,** written once and shaped like llama.cpp's OpenAI-compatible chat API. It streams fixed tokens at a set pace. It isolates the backend's cost, its HTTP client included: opening and pooling connections, reading the upstream's stream, and turning its chunks into the contract's events.
- **An in-process fake** in each backend, as ai-bootstrap's `LLM_PROVIDER=fake`. It's paced like the fake server, and isolates serving alone: HTTP, JSON and writing the events.

The gap between the two fakes' results is a number of its own: what calling out costs in each language.

Two rules keep them fair:
- **Both fakes behave the same:** the same tokens, the same time to the first, the same gap between them. The contract states it, and the evaluation tool checks it before measuring.
- **The fake server is measured on its own first,** to show it reaches well beyond any backend's ceiling.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| llama.cpp alone | The model's seconds hide the backend's cost, and its few slots cap the load. |
| The fake server alone | It loses the serving-only number, and the owner's flag. |
| The in-process fake alone | It misses the HTTP client's path, which is most of an AI backend's work. |

## Consequences

- Each language has fake code to keep identical, checked by the conformance suite.
- The fake server must be written in a language fast enough not to be the bottleneck, and proven so (step 2.1).
- Reports show every number with its upstream, never mixed.

## Assumptions to verify

- [ ] The fake server reaches a rate well above every backend's ceiling on the same machine.
- [ ] Each language's timers keep the fakes' pace accurately at the gaps we use.
- [ ] llama.cpp's stream can be imitated closely enough that a backend's code can't tell the fake server from it.

## Sources

- [Bifrost's benchmarks](https://www.getmaxim.ai/bifrost/resources/benchmarks), read on 2026-11-05.
- [llama.cpp's server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), read on 2026-11-05.
- ai-bootstrap's [LLM port](https://github.com/fkuhne/ai-bootstrap/blob/main/docs/foundations.md#the-llm-port) and its `FakeLLMClient`.
