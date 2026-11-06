# 0006. A remote upstream: Ollama Cloud, beside a local imitation

- Status: Proposed
- Date: 2026-11-06

## Context

The owner wants to measure how each backend deals with an external API, through Ollama Cloud (2026-11-06). The owner has a key, and Ollama Cloud's free models cost nothing.

A remote upstream adds what the local ones can't show:
- **TLS and connection reuse** to a remote host: the handshake's cost, keep-alive, and HTTP/2 or not. Each language's HTTP client differs here.
- **A real provider's behaviour:** network jitter, a varying time to first token, and 429s.

It also has limits:
- **Noise.** The internet and the provider vary far more than the backends do.
- **Low rates.** Third-party pages report one concurrent cloud model on the free plan and three on Pro, with limits reset every 5 hours, and no published requests per minute. This is unchecked against ollama.com ([notes](../../docs/benchmarking.md#ollama-cloud)).
- **Readers can't repeat it** exactly: the provider changes.

## Decision

Two parts:
- **A repeatable imitation of a remote API:** the fake upstream server over HTTPS, behind a network emulator such as Toxiproxy, which adds latency, jitter, bandwidth limits and dropped connections at any load. The emulator is measured on its own first.
- **Ollama Cloud** at `https://ollama.com/v1`, on one free model, as the check against reality. It runs at low rates, with the backends interleaved (Python, Go, Python, Go) and repeated. Each result carries its date.

The emulator and its settings are plan step 4.1.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| Ollama Cloud alone | Noisy, rate-limited, and readers can't repeat it. |
| The imitation alone | Nothing would show that it resembles a real API. |
| No remote upstream | It misses TLS and connection reuse, which every backend calling a provider pays for. |

## Consequences

- The key lives in `.env`, never in git. CI runs without it ([0009](0009-publish-as-a-public-github-repository.md)).
- The free plan's limits are checked on ollama.com before step 4.2.

## Assumptions to verify

- [ ] Ollama Cloud's free models allow the low-rate runs we plan.
- [ ] The emulator adds little enough of its own not to hide the backends' differences.
- [ ] Ollama Cloud's chat API is OpenAI-compatible enough for the backends' one client. ai-bootstrap's live tests pass against it.

## Sources

- ai-bootstrap's [`docs/llms.md`](https://github.com/fkuhne/ai-bootstrap/blob/main/docs/llms.md), read on 2026-11-06.
- Third-party summaries of Ollama Cloud's plans, read on 2026-11-06, listed in the [notes](../../docs/benchmarking.md#ollama-cloud).
- A guide to [Toxiproxy in Docker](https://oneuptime.com/blog/post/2026-02-08-how-to-use-docker-for-chaos-engineering-with-toxiproxy/markdown), read on 2026-11-06.
