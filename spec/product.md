# api-langs-bench: product spec

This is the source of truth for what the project covers and what it doesn't. A change of scope starts here, then flows into [`requirements.md`](requirements.md), [`plan.md`](plan.md) and the [decision records](decisions/README.md).

> **Written 2026-11-06** from the owner's interview on 2026-11-05 and 2026-11-06. The owner picked the name and the licence on 2026-11-06 (step 0.2).

## The problem

The owner builds backends for AI apps. Such a backend takes a chat request, calls an LLM, streams the tokens back, and stores the conversation. The owner wants three things from building the same backend in several programming languages:
- **to pick a stack:** which language serves an AI backend best, and at what cost;
- **to learn:** how each language and its ecosystem do the same job;
- **to publish:** a comparison that others can read and repeat.

The shortcuts don't answer it. As read on 2026-11-05 ([notes](../docs/benchmarking.md#prior-art)):
- **General web benchmarks** test plain HTTP work: JSON, database queries, plain text. TechEmpower's was archived in March 2026; HttpArena is its successor. Neither has a backend that streams from an LLM.
- **LLM gateway benchmarks** do compare languages on this job, such as Bifrost (Go) against LiteLLM (Python). But a vendor runs them on its own product, and publishes the numbers without a harness a reader can rerun.
- **LLM load tools,** such as GenAI-Perf and GuideLLM, measure the model's server, not the backend in front of it.
- **Small repositories** compare languages as REST APIs, such as the code of an InCIT 2023 paper. They test plain REST, with no stream behind it.

There's also a trap in measuring this naively. A real model's reply takes seconds, and a backend's own cost is micro- to milliseconds. Measured only against a real model, the language's cost disappears.

## Who it's for

1. **The owner,** choosing the language for their own AI backends, and learning each language by building the same service in it.
2. **Engineers building similar backends.** They can read every line of each backend and repeat every run.
3. **Tech leads** looking for numbers to support a decision, with how each was measured.
4. **A coding agent** working with the owner. It needs the spec, the notes and the records to pick up where the last session stopped.

## What it is

A benchmark, in a public GitHub repository, run with Docker Compose on any machine. It holds:
- **Backends, one per programming language,** Python and Go first. Each implements the same API: [ai-bootstrap](https://github.com/fkuhne/ai-bootstrap)'s chat, as a whole answer or a stream of server-sent events, with its readiness check and its errors. In version 1's last phase, conversations stored in PostgreSQL too. Text only.
- **Upstreams, picked by a setting,** the same for every backend:
  - **llama.cpp's server,** with one small model, pinned: the real thing, so we can see it work;
  - **a fake upstream server,** written once and shaped like llama.cpp's API. It streams fixed tokens at a set pace, so each backend's own cost shows, its HTTP client included;
  - **an in-process fake** in each backend, paced like the fake server. It is the flag that bypasses the LLM, and measures how each language serves alone;
  - **a remote API:** the fake server over HTTPS behind a network emulator, for repeatable runs, and Ollama Cloud, as the check against reality.
- **An evaluation tool.** It sends every backend the same workloads and records what each does:
  - whole and streamed requests, at fixed arrival rates;
  - a ramp, to find each backend's ceiling;
  - many open streams at once;
  - clients that leave mid-stream.
- **Runs, each saved once,** with its settings, its versions and the machine it ran on.
- **A web UI** that starts a run through the same runner, and shows the runs and a comparison of the backends.

## Outcomes

*Accepted as a first draft on 2026-11-06, to be tuned as the work teaches us.*

- **One table per backend, upstream and workload,** measured on the same machine:
  - **latency:** p50, p95 and p99, whole and streamed;
  - **time to first token** through the backend, and the time the backend adds over its upstream;
  - **stream behaviour:** the jitter the backend adds between tokens; whether it passes each token on at once or buffers them; how fast a client's leaving stops the upstream;
  - **throughput** at fixed rates, and the ceiling: the rate where latency or errors cross a written threshold;
  - **errors** under load;
  - **resources:** memory (idle and peak), CPU, image size and start-up time.
- **With conversations:** the time the history's read adds before the first token, the time storing the turn adds after it, and what happens when streams outnumber the database's connections.
- **A run anyone can repeat** with one command, on pinned versions, on their own machine.
- **A published report** a tech lead can cite, each number with its run and its machine.
- **A web UI** that runs the benchmark and shows its results.

## Scope

**Version 1:**
- **Python and Go backends,** one framework each: FastAPI for Python, as in ai-bootstrap; the Go one is picked in a plan step.
- **Stateless chat,** whole and streamed.
- **All the upstreams:** the in-process fake, the fake server, llama.cpp on CPU, the remote imitation and Ollama Cloud.
- **The evaluation tool,** with the workloads above, stream behaviour included.
- **The same limits for every backend:** each in its own container, with the same CPU and memory.
- **Conversations on PostgreSQL,** as the last backend phase, once stateless chat is measured from end to end.
- **The web UI,** as the last step.
- **The first report.**

**Next:**
- **More languages:** Rust, Java, JavaScript and C++, one at a time, in an order picked then. An `add-language` skill, written from what Python and Go taught, makes each one routine.
- **More than one framework or runtime per language,** such as FastAPI against Litestar, Go's standard library against a framework, or free-threaded Python.
- **The developer's side:** lines of code, dependencies, build time, and notes on what was hard in each language.
- **The post,** on LinkedIn and X.

**Later, as ideas:**
- llama.cpp on a GPU.
- Other cloud providers as upstreams.
- Behaviour under failure: an upstream that fails or hangs, timeouts and retries.
- A small benchmark in CI on every push.
- A guide for others to contribute a language.

## Non-goals

- **Scoring the model's answers.** The LLM is a means, not the subject: this isn't an LLM eval.
- **Ranking many frameworks,** as TechEmpower did. We go deep on a few implementations, and readers can see every line of each.
- **Code tuned only to win.** Each backend is written the way a competent engineer would write it, following its ecosystem's documented production set-up. The exact rule becomes a record (plan step 3.1).
- **Login.** The owner's focus is the backend for AI: chat, streaming and their metrics. Conversations take the user from `X-User-Id`, as ai-bootstrap does.
- **Images, audio and tools in messages,** for now. Text only, so every language does the same work.
- **RAG, agents, and modules beyond chat and conversations.**
- **A chat UI.** The web UI runs the benchmark; it isn't an app to chat in.
- **A paid dependency.** Everything runs locally. Ollama Cloud is optional, on its free models.

## Constraints

- **Resources are stated, not assumed.** Each step says what it needs: memory, disk, time and money. Each measurement names the machine it ran on.
- **Machines:** runs happen on any machine with Docker, this one or another. None is fixed, and no machine's size bounds the design. Each run records the machine it ran on ([0008](decisions/0008-run-anywhere-with-docker-and-record-the-machine.md)).
- **Money:** nothing is spent. Ollama Cloud's free models need only a key, which the owner has. Any spend gets a record first.
- **Time:** no target date, for the report or the post.
- **Public from the first commit:** keys and secrets stay in `.env`, never in git ([0009](decisions/0009-publish-as-a-public-github-repository.md)).
- **Nothing large in git.** Models, results too large to read, and images stay out of it.
- **English** everywhere: code, notes and records.

## Open questions

None open. Answered by the owner at step 0.2, on 2026-11-06 ([0009](decisions/0009-publish-as-a-public-github-repository.md)):
- **The name:** `api-langs-bench`. "langs" means programming languages, and "bench" is the word readers search for.
- **The licence:** MIT No Attribution (MIT-0), as in ai-bootstrap, so readers can copy any backend freely.
