# 0026. Runs against the local upstreams: the upstream alone as the baseline, a rung at 200, and llama.cpp one request at a time

- Status: Accepted
- Date: 2026-11-13

## Context

Plan step 2.4 runs every backend against its three local upstreams, and works out the time each backend adds over its upstream (R8). The runner so far sends one workload, `stream-20`, to each backend's in-process fake, at four rates, in three passes ([0018](0018-the-first-runner-oha-as-the-load-generator-one-streamed-workload-and-runs-committed-as-json.md), [0020](0020-the-first-numbers-a-ladder-of-rates-under-provisional-limits-three-passes.md)). Since plan steps 2.1 to 2.3, a backend can also answer through the fake server or llama.cpp ([0023](0023-the-fake-upstream-server-go-in-its-own-module-shaped-as-llama-cpps-chunks.md), [0024](0024-each-backends-upstream-client-its-plain-http-client-one-pool-setting-no-retries.md), [0025](0025-llama-cpp-in-compose-qwen3-5-0-8b-four-slots-a-pinned-file.md)).

What was read and run on 2026-11-13:

- **oha's "first byte" is the first token.** In oha 1.16.0's `client.rs`, it's stamped when the first frame of the response's body arrives, after the headers. A backend sends its headers at once, so the first frame is its first event.
- **It isn't corrected for waiting.** It counts from when the request was sent, not from when it was due (`result_data.rs`). Under overload it leaves the queue out: on the Mac, Python at 500 a second had a first byte at 461 ms beside a latency of 3,184 ms ([backends](../../docs/backends.md#the-upstream-client)).
- **The fake server alone is late too,** by about 1.2 ms at the median under load on the Mac: 241.2 ms against 240 ms due ([fake server](../../docs/fake-server.md#measured-alone-on-2026-11-10)). Through it, at 100 a second, Go ended at 242.4 ms and Python at 244.5 ms.
- **On the owner's Windows machine, Python kept 100 a second only** from its in-process fake, and answered about 300 at most ([runner](../../docs/runner.md#the-first-numbers-on-2026-11-10-on-a-core-i7-12850hx)). Calling an upstream costs more.
- **llama.cpp's own time varies far more than a backend adds.** The same request, 20 tokens, with a seed, a temperature of 0 and reasoning off, 20 times each, one at a time, on the Mac:

  | Path | Median | Fastest to slowest |
  |---|---|---|
  | Straight to llama.cpp | 222.4 ms | 212.7 to 259.8 ms |
  | Through Go, `net/http` | 223.9 ms | 212.9 to 285.9 ms |
  | Through Python | 228.2 ms | 213.3 to 275.6 ms |

## Decision

The runner runs each backend from both fakes by default, and from llama.cpp when asked. The time a backend adds is its median less the median of a run of the upstream alone, in the same pass.

- **`--upstream`** names an upstream: `fake`, the in-process fake; `fake-server`; or `llama-cpp`. It may be given more than once. Without it, the runner runs `fake` and `fake-server`. llama.cpp must be started first, since it needs its model ([0025](0025-llama-cpp-in-compose-qwen3-5-0-8b-four-slots-a-pinned-file.md)).
- **The upstream alone is a run of its own.** For the fake server and llama.cpp, each pass also sends the same load straight to the upstream: the request a backend's client sends it, at the same rates. It takes its turn with the backends in the pass's rotation.
- **The time a backend adds** is worked out for each pass and rate: the backend's p50 less the upstream's own, for the whole stream and for the first token. The table gives the median of these over the passes, and their range. It gives none when either run didn't keep its rate.
- **The in-process fake has no upstream to run alone.** Its rows keep their latency beside the timetable's 240 ms, as before.
- **The time to the first token** is oha's first byte, read only from runs that kept their rate.
- **The ladder gains a rung:** 100, 200, 500, 1,000 and 2,000 requests a second, still provisional until plan step 3.2.
- **llama.cpp is run one request at a time:** 30 requests of 20 tokens, each sent when the last has ended, after 3 that aren't counted. Each carries a seed, a temperature of 0, and reasoning off, so the model does the same work every time. It's a closed loop by intent: it compares paths, not rates.
- **A run's file** names its upstream and records the upstream's image; its name carries both the backend and the upstream. The file's `schema` becomes 3.
- **Both fakes get the same settings,** and a new container for every run, the fake server too. llama.cpp keeps running between runs: it takes seconds to load.
- **A backend waits for its upstream as the contract's default says,** 300 s: a run shows a slow upstream as slow, not as a 504.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| The added time against the timetable: the median less 240 ms | No extra runs. But it counts the fake server's own lateness, and the load generator's, as the backend's |
| Request by request, from the fake server's log | Exact for every request. But the fake server would log every request, which costs it, and the tool would join two records: closer to plan step 3.3 |
| The ladder as it was | The first numbers' rates. But Python would probably keep only one of them through an upstream |
| Several new rungs | A finer picture of each ceiling. But longer, and the real rates are plan step 3.2's |
| llama.cpp at a fixed rate | The same shape as the other runs. But with 4 slots, its queue would be most of every number |
| No timed runs of llama.cpp | Nothing to build. But the plan's three upstreams would have numbers for two |

## Consequences

- A full run takes longer: 35 runs a pass, about 24 minutes, so about 72 minutes for three passes (computed), against 25 before.
- The runs of the fake server alone also check R4 on the machine that makes the numbers: they show whether it kept every rate there.
- The difference of two medians isn't a median of differences. It's a fair account of the typical request, and says nothing of the tail; plan step 3.3 measures each event.
- With llama.cpp, the honest result may be that a backend's cost doesn't show beside the model's own spread.
- Runs made before this record have `schema` 2 and no upstream in their names.

## Assumptions to verify

- [ ] The time a backend adds, worked out this way, is steadier from pass to pass than the backend's own median. To check with the first runs. *2026-11-13, on the Mac: not through llama.cpp. Over three passes, Python's added time ranged from -11.3 to +9.9 ms, against 266.8 to 279.9 ms for its own median: the model's own spread is in both runs, and doesn't cancel. From the fakes, one pass only, so still to see ([runner](../../docs/runner.md#a-check-of-the-upstreams-runs-on-2026-11-13)).*
- [ ] The fake server alone keeps every rate of the ladder on the machine that makes the numbers. To check with those runs. *2026-11-13, on the Mac: it kept every rate to 2,000 a second, with a p50 of 241.0 to 241.2 ms and every answer whole ([runner](../../docs/runner.md#a-check-of-the-upstreams-runs-on-2026-11-13)).*
- [x] With a seed and a temperature of 0, llama.cpp makes the same 20 tokens every time, so every request is the same work. To check in this step. *2026-11-13: six requests returned the same 20 tokens, "An LLM is a large language model that uses artificial intelligence to process and generate human-like text," (our run).*
- [ ] 1,000 connections bind no backend at these rates ([0024](0024-each-backends-upstream-client-its-plain-http-client-one-pool-setting-no-retries.md)). To check with the first runs. *2026-11-13, on the Mac: both Go servers kept 2,000 a second through the fake server, about 480 streams open at once, so they weren't bound. Python ran out of CPU first, near 390 a second.*

## Learned while building it

- **A 200 isn't always an answer.** A stream answers 200 once its request is valid, and an upstream's failure then comes as an `error` event in a short body. In the first check, Python through the fake server at 2,000 a second had a p50 of 1.9 ms. So each run keeps one whole answer's size before it starts, records whether every answer was whole, and no added time is worked out from a run that wasn't. Through llama.cpp, whose answers vary in size, only the statuses are checked.
- **llama.cpp closes its connection after every stream,** though its headers say keep-alive. oha counted the next request on such a connection as failed, so one request at a time goes on a new connection each time.
- **Through llama.cpp, a backend's cost doesn't show,** as expected: the model's own median moved by 25 ms from one pass to the next ([runner](../../docs/runner.md#a-check-of-the-upstreams-runs-on-2026-11-13)).
- **Through the fake server on the Mac,** Go added 0.2 to 0.9 ms, and Python 2.0 to 3.3 ms, and Python ran out between 200 and 500 a second.
- **llama.cpp's v1.0.0 came out on 2026-11-13,** as build `b12359`. Its `server` image's stream and whole answer have the same fields, in the same order, as `b12242`'s, which stays pinned for now ([0025](0025-llama-cpp-in-compose-qwen3-5-0-8b-four-slots-a-pinned-file.md)).

## Sources

- [oha 1.16.0's `client.rs` and `result_data.rs`](https://github.com/hatoo/oha/tree/v1.16.0/src), read on 2026-11-13.
- Our runs on the Mac on 2026-11-13: the same request to llama.cpp, 20 times straight and 20 times through two backends.
- Our runs of 2026-11-10 ([runner](../../docs/runner.md), [backends](../../docs/backends.md#the-upstream-client), [fake server](../../docs/fake-server.md)).
- The check's 47 runs, 2026-11-13 ([runner](../../docs/runner.md#a-check-of-the-upstreams-runs-on-2026-11-13)).
- The owner's picks, 2026-11-13.
