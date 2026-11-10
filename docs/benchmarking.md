# Benchmarking an AI backend across languages: notes

What we know about benchmarking an AI backend written in several programming languages, each claim with its source: a paper's section or table, a vendor page, the code, documentation, or a run of ours, with the date it was checked. A number worked out but not yet run is marked "computed". A claim from memory is marked "unchecked". A claim read only in a search engine's summary, not on the page itself, says so.

## Prior art

### General web benchmarks

- **TechEmpower's Framework Benchmarks** were archived on 2026-03-24. The last full round, 23, came out in February 2025 and covered more than 330 implementations. They test plain HTTP work: JSON, plain text, database queries and templates. *Sources:* [a DEV post on the archive](https://dev.to/kaliumhexacyanoferrat/techempower-framework-benchmarks-are-now-archived-whats-next-3l0a) and [a news summary](https://news.lavx.hu/article/techempower-framework-benchmarks-sunset-after-13-years-of-community-driven-performance-testing), from a search on 2026-11-05. The official announcement wasn't read.
- **[HttpArena](https://github.com/MDA2AV/HttpArena/wiki)** is the most visible successor. It runs 27 test profiles on 64-core dedicated hardware: connections, JSON, compression, databases, templates, HTTP/2 and HTTP/3, gRPC and WebSocket echo. Results go to a public leaderboard, and runs can be started from pull requests. *Source:* a search summary of its wiki, 2026-11-05; the wiki not read in full.

**What they miss for us:** neither has a backend that calls an upstream and streams its answer back.

### LLM gateways compared across languages

**Bifrost (Go) against LiteLLM (Python),** on [Maxim's benchmarks page](https://www.getmaxim.ai/bifrost/resources/benchmarks). Maxim makes Bifrost. Read on 2026-11-05; the page has no date, and doesn't say whether its harness is published.
- **Set-up:** AWS t3.medium (2 vCPU, 4 GB), us-east-1, 60 seconds, 500 requests per second from 500 virtual users. The upstream was a mock OpenAI response with 60 ms of latency. The load tool isn't named.
- **Overhead test:** median end-to-end 60.99 ms against 100 ms, so 0.99 ms of overhead against 40 ms.
- **At 500 requests per second:**

  | | Bifrost | LiteLLM |
  |---|---|---|
  | Success | 100% | 88.78% |
  | p50 | 804 ms | 38.65 s |
  | p99 | 1.68 s | 90.72 s |
  | Throughput | 424 req/s | 44.84 req/s |
  | Peak memory | 120 MB | 372 MB |

- **Bifrost alone at 5,000 requests per second:** 59 µs of overhead on a t3.medium, 11 µs on a t3.xlarge.
- **Our reading, not the page's:** with a 60 ms upstream, a p50 of 804 ms means requests queued even in Bifrost. The page doesn't say where.

**[Preto.ai's write-up](https://dev.to/gauravdagde/we-evaluated-go-rust-and-python-for-our-llm-proxy-go-won-and-not-for-the-reason-youd-expect-4a2j),** "We evaluated Go, Rust and Python for our LLM proxy". Posted on 3 April, year not shown; read on 2026-11-05.
- **No set-up is described:** no load tool, upstream or hardware. Its Python numbers come from LiteLLM's published benchmarks.
- **Its figures:** Go about 11 µs of overhead at 5,000 requests per second; Rust under 1 ms p99 at 10,000; Python (LiteLLM) about 40 ms at 500.
- **Its conclusion:** Go, chosen for development speed, hiring and a simpler middleware model, not for raw speed. It's a vendor's post.

**TensorZero (Rust):** one search on 2026-11-05 found no published numbers against a mock provider.

**What they teach us:**
- **Overhead is measured against a mock upstream,** with a known latency, which [0004](../spec/decisions/0004-three-local-upstreams-llama-cpp-a-fake-server-and-an-in-process-fake.md) follows.
- **Load tests and overhead tests answer different questions.** One gateway's overhead was 40 ms in one test, and its p50 38 s in the other.
- **None publishes a harness** a reader can rerun.

### Languages compared as REST APIs

**[`ultramcu/api-lang-bench`](https://github.com/ultramcu/api-lang-bench),** the code of Tanadechopon and Kasemsontitum, "Performance Evaluation of Programming Languages as API Services for Cloud Environments", InCIT 2023. Its README was read on 2026-11-05.
- **Stacks:**
  - PHP 8 on Apache, and on nginx with php-fpm;
  - Node.js 18 with Express;
  - Python 3.9 with Flask and PyMySQL;
  - Go 1.18 with Echo.
- **Endpoints:** a login, n rows as JSON, a file upload, and a CPU-bound π calculation. They share one MariaDB.
- **Method:** JMeter 5.6.2, with 1 and 100 concurrent users and 100 iterations each. The APIs ran on DigitalOcean droplets with 2 vCPU and 4 GB. The client was a MacBook on a 100 Mbit/s switch.
- **Results:** Go was fastest at 100 users. Python with Flask was slowest under load, with low CPU use. At 100 users, uploads saturated the network before the languages differed.
- **What it teaches us:**
  - **The framework can decide more than the language.** Flask is synchronous, and Python's async frameworks behave differently ([R6](../spec/requirements.md)).
  - **A saturated helper measures the helper,** here the network ([R4](../spec/requirements.md)).

**Several small `backend-language-benchmark` repositories** exist on GitHub, seen by name only on 2026-11-05.

### Load tools for LLM servers

These measure a model's server, not a backend in front of it. Their metrics are still the vocabulary readers know, and one could serve as our load generator for streamed runs (plan step 1.6).
- **[GenAI-Perf](https://docs.nvidia.com/nim/benchmarking/llm/latest/metrics.html) (NVIDIA)** reports output token throughput, time to first token, time to second token, inter-token latency and request throughput, against any OpenAI-compatible endpoint.
- **LLMPerf (Ray)** is archived.
- **GuideLLM (Red Hat)** runs against OpenAI-style chat endpoints. Its definitions weren't checked.

*Source:* search summaries of NVIDIA's documentation and [a DEV post](https://dev.to/wheynelau/how-to-benchmark-llm-inference-performance-ttft-itl-and-throughput-metrics-416p), 2026-11-05.

## Metrics: the same names, different definitions

As summarised by a search on 2026-11-05, from NVIDIA's documentation and the DEV post above:
- **Time to first token:** tools skip first chunks with empty content. It includes queueing, prefill and the network.
- **Inter-token latency:** GenAI-Perf computes it as (end-to-end latency − time to first token) / (output tokens − 1). LLMPerf includes the time to first token in its average.
- **Throughput:** LLMPerf divides the output tokens by the whole benchmark's duration. GenAI-Perf divides by the span from the first request to the last response.

**For us:** each metric gets one written definition (plan steps 3.2 and 3.3). The time a backend adds is measured against an upstream whose own timing is known.

## Measuring latency without fooling ourselves

- **Coordinated omission** is Gil Tene's name for how closed-loop tools under-report tail latency. While the system is slow, they stop sending, so the slow period is under-sampled.
- **Open and closed models:** in [k6's closed model](https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/open-vs-closed/), the default, a virtual user's next iteration starts only when the last one ends. Its arrival-rate executors are open: requests arrive at a set rate, whatever the server does.
- **wrk2** sends at a constant rate, and its latency includes the time queued.
- **Vegeta** is open-loop.
- **oha** has a `--latency-correction` flag, which counts a request's latency from when it was due. With too few connections on purpose, its p50 was 3.2 s corrected and 241 ms not. Requests still due when the time ends are never sent, so the rate reached must be checked too ([our run, 2026-11-09](runner.md#the-load-generator-measured-alone)).

- **A client that leaves may not close its connection at once.** Go 1.27.3's HTTP client, when a response's body is closed early, reads on for up to 50 ms or 256 KiB to reuse the connection, then closes it (`maxPostCloseReadTime`, in `net/http/transport.go`). A backend sees the client leave only then: 51 ms late, in our run ([backends](backends.md#go-nethttp)). The load generator that measures a client's leaving (plan step 3.3) must close its connection, such as with keep-alive off.

*Sources:* k6's documentation, and search summaries of [a DEV post on coordinated omission](https://dev.to/speed_engineer/coordinated-omission-why-your-load-testing-tool-is-lying-about-your-p99-4p7k) and tool comparisons, 2026-11-05.

## The upstreams

### llama.cpp's server

From [its README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), read on 2026-11-05:
- **`GET /health`** answers 503 while the model loads, and 200 once it's ready.
- **OpenAI-compatible chat completions,** streamed over server-sent events with `"stream": true`. The route's details weren't in the part of the page read. ai-bootstrap calls it at `/v1` ([its `llms.md`](https://github.com/fkuhne/ai-bootstrap/blob/main/docs/llms.md)).
- **`GET /slots`** shows each slot. With `?fail_on_no_slot=1`, it answers 503 when no slot is free.
- **`--metrics`** turns on a Prometheus endpoint. It's off by default (`LLAMA_ARG_ENDPOINT_METRICS`).
- **`-np, --parallel N`** sets the number of slots. The default, `-1`, picks one automatically (`LLAMA_ARG_N_PARALLEL`).
- **Continuous batching** is on by default.
- **Answers carry `timings`,** such as `predicted_per_second`.
- **Images:** `ghcr.io/ggml-org/llama.cpp:server`, and `:server-cuda` for NVIDIA.

### Ollama Cloud

- **The API:** `https://ollama.com/v1`, with a key from ollama.com/settings/keys. ai-bootstrap's live tests pass against it, with `gemma4:31b` ([ai-bootstrap's `llms.md`](https://github.com/fkuhne/ai-bootstrap/blob/main/docs/llms.md), read on 2026-11-06).
- **Plans,** unchecked against ollama.com. From third-party pages read on 2026-11-06, such as [a DEV post](https://dev.to/amareswer/ollama-cloud-free-vs-pro-usage-limits-pricing-what-you-actually-get-2026-3ieo) and [a mirror of Ollama's page](https://registry.ollama.ai/cloud):
  - the free plan gives "light" usage, with no published allowance;
  - Pro costs $20 a month for 50 times the free usage, and Max $100 a month for 5 times Pro;
  - session limits reset every 5 hours, and weekly ones every 7 days;
  - one cloud model at a time on the free plan, three on Pro and ten on Max;
  - no requests-per-minute figure is published.
- **The owner,** 2026-11-06: free models cost nothing with a key.

### Toxiproxy

A TCP proxy placed between two services. Its "toxics" add latency (plus or minus a jitter), limit bandwidth, add timeouts, reset connections or cut a proxy off. Its control API listens on port 8474, and its image is `ghcr.io/shopify/toxiproxy`. *Sources:* [a guide to Toxiproxy in Docker](https://oneuptime.com/blog/post/2026-02-08-how-to-use-docker-for-chaos-engineering-with-toxiproxy/markdown) (2026-02-08) and Testcontainers' documentation, from a search on 2026-11-06. The official README wasn't read.

Since it works on TCP, TLS should pass through it untouched, with the fake server ending TLS itself. *Unchecked.*

## The contract's source: ai-bootstrap's chat

[ai-bootstrap's foundations](https://github.com/fkuhne/ai-bootstrap/blob/main/docs/foundations.md#chat-whole-or-streamed), read on 2026-11-05:
- **Two endpoints.** `POST /api/chat` returns the whole answer. `POST /api/chat/stream` sends `reasoning` and `token` events, then `done` (model, finish reason, usage) or `error`. Both are stateless.
- **The body:** `{"messages": [...], "parameters": {...}}`.
- **The errors:** 502, 503, 504 and 429, each with its reason.
- **Conversations** are a module of their own, on PostgreSQL. A turn is stored only once its answer is complete.

**Its code,** at [`edc0565`](https://github.com/fkuhne/ai-bootstrap/tree/edc0565) of the public repository, read on 2026-11-06:
- **A stream starts with 200** once the body is valid. Every upstream failure inside it, even before the first token, becomes an `error` event ([router.py:40-45](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/modules/chat/router.py#L40-L45)).
- **The upstream's chunks.** Each becomes at most one `reasoning` event and one `token` event, and a chunk without text sends nothing. The reasoning is read from `reasoning_content` (llama.cpp, DeepSeek) or `reasoning` (Ollama) ([openai_compatible_client.py](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/llm/openai_compatible_client.py)).
- **Free parameters** go to the upstream through the OpenAI SDK's `extra_body`. The usage comes in a last chunk, asked for with `stream_options.include_usage`. Closing the upstream's response is how a client's leaving stops the model.
- **The fake** echoes "Fake answer to: <question>", one word per token, with no pacing ([fake_llm_client.py](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/app/llm/fake_llm_client.py)).

**FastAPI 0.143.0,** the version ai-bootstrap pins. Read in its wheel from PyPI on 2026-11-06, in `fastapi/sse.py`, `routing.py`, `exception_handlers.py` and `applications.py`:
- **Each event** is an `event:` line, a `data:` line and a blank line. A model's data is written with `model_dump_json()`: compact, with nulls included.
- **After 15 seconds with no event,** it sends the comment `: ping`.
- **The headers** are `Content-Type: text/event-stream`, `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
- **An invalid body** answers 422 with `{"detail": [ … ]}`, a list of the validation errors.
- **The OpenAPI it generates** is version 3.1.0.

What we keep of it is in [`contract/`](../contract/README.md), and why is in [0010](../spec/decisions/0010-the-contract-ai-bootstraps-chat-in-text-paced-fakes-and-openapi-3-2.md).

## Describing a stream in OpenAPI

- **OpenAPI 3.2.0 (September 2025)** adds sequential media types, `text/event-stream` among them. An `itemSchema` describes one event, after parsing ([the specification](https://spec.openapis.org/oas/v3.2.0.html), §4.14.4, and the example "Server-Sent Event Streams", read on 2026-11-06).
- **An event's `data` is a string.** The JSON inside it is described with `contentMediaType` and `contentSchema`, which validators don't check by default (same section). A conformance check has to parse the data and validate it against the event's schema itself.
- **The order of events,** such as "exactly one `done` at the end", can't be expressed. Our contract states it in prose.
- **Tools:** Redocly CLI says it supports 3.2, but on weak sources ([OpenApi.tools](https://openapi.tools/tools/redocly-cli/), [a mirror of its README](https://awesome.ecosyste.ms/projects/github.com%2Fredocly%2Fredocly-cli), read on 2026-11-06). Nothing was found for Spectral or Swagger UI. To check in plan step 1.2.

## Docker and the numbers

- **Docker Desktop** on macOS and Windows runs containers inside a Linux VM. *Unchecked.*
- **Timers in Docker's VM:** on Colima on the owner's M3, a 20 ms sleep in a container wakes 4 to 7 ms late at the median, and up to 13 ms at p99 (our runs, 2026-11-06 and 2026-11-09, [backends](backends.md#timers-in-dockers-vm-on-this-mac)).
  - **The cause is the VM's idle virtual CPUs.** With all four kept busy, the same sleep wakes 0.07 ms late at the median.
  - **So the VM can change how backends compare,** not only the absolute numbers: a backend that burns more CPU keeps the VM busier, and its paced fake runs closer to time (computed from these runs, not yet shown with two backends).
  - **macOS's own sleeps** are 1 to 5 ms late, without Docker (our run, 2026-11-09).
- **Docker on native Linux:** a container is a process on the host's kernel, with its CPU and timers. Docker's NAT adds latency at high packet rates, and host networking matches native ([Felter et al., IBM, 2014](https://www.read.seas.harvard.edu/~kohler/class/cs260r-s19/containerperf14.pdf), Redis's latency, read through [a review](https://souptikji.github.io/blog/2018/04/Containerization) and search summaries; unchecked against its tables).
- **For us:** the report's timing numbers come from native Linux ([0015](../spec/decisions/0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)).
- **Docker's CPU limits:** `--cpus` limits a share of CPU time, and `--cpuset-cpus` pins a container to cores. *Unchecked.* Which one we use is plan step 3.1.

## Open questions

Questions the sources don't answer yet. Each moves into the notes, with its source, once answered.

- How does llama.cpp's server chunk its stream: one token per event, and with which fields? The fake server must imitate it (plan step 2.1).
- What are Ollama Cloud's real limits on the free plan (plan step 4.2)?
- Is Bifrost's benchmark harness published anywhere? If so, we could run its method.
- Does a Python backend need several worker processes to compete fairly, and how does that fit a CPU limit (plan step 3.1)?
- What does each ecosystem document as its production set-up: for Python, uvicorn's or Gunicorn's workers; for Go, `GOMAXPROCS` in a container (plan steps 1.3, 1.4 and 3.1)?