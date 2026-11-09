# AGENTS.md

Instructions for coding agents working in this repository. Keep this file short: detail belongs in `spec/` and `docs/`, read when a step needs it.

## What this is

A benchmark of the same AI backend written in several programming languages: Python and Go first, then Rust, Java, JavaScript and C++. Every backend serves one chat API, taken from [ai-bootstrap](https://github.com/fkuhne/ai-bootstrap), whole and streamed. Behind it sits an LLM: llama.cpp locally, Ollama Cloud remotely, or fakes that isolate the backend's own cost. An evaluation tool sends every backend the same load, and records its latency, its stream's behaviour, its throughput and its resources.

What the project covers is in [`spec/product.md`](spec/product.md). What we know about benchmarking an AI backend, with sources, is in [`docs/benchmarking.md`](docs/benchmarking.md).

## Read before acting

1. [`spec/product.md`](spec/product.md): what we do and what we don't. It's the source of truth for scope.
2. [`spec/requirements.md`](spec/requirements.md): each requirement, how it's met and how it's verified.
3. [`spec/plan.md`](spec/plan.md): the steps, in order. The next step is the first unticked one.
4. [`spec/decisions/README.md`](spec/decisions/README.md): the decision records that touch the step.
5. [`docs/benchmarking.md`](docs/benchmarking.md): the notes, for the sections the step relies on.

## How we work

- **One plan step at a time.** Before a step with design choices, lay out the options, the evidence and a recommendation, and let the owner pick. Don't decide a whole step alone.
- **Show evidence the owner can see:** real output and real numbers, such as scores, time, peak memory and disk use. Not just "it ran".
- **Write down what a step measures,** in `docs/`, with its command, its settings and the machine it ran on.
- **Source every claim in the notes:** a paper's section or table, a model card, a config, the code, a vendor page, or our own run. A number worked out but not yet run is marked "computed". A claim from memory is marked "unchecked".
- **A record for every decision**, from [`spec/decisions/decision-template.md`](spec/decisions/decision-template.md), committed on its own or with the change it justifies.
  - Proposed becomes Accepted in the commit that implements it.
  - A reversed decision gets a new record, and the old one is marked superseded.
- **Guesses go under "Assumptions to verify"**, ticked with evidence once checked.
- **Small commits.** Each one is a coherent increment, and none references files that only arrive later. Tick the plan step in the commit that finishes it.
- **A change of scope starts in `spec/product.md`.** When the work departs from the plan, update the plan in the same change.
- **After a step,** explain what was built or learned and why, with links to the lines, before moving on.
- **Skills** run these routines:
  - [`next-step`](.agents/skills/next-step/SKILL.md) prepares the plan's next step;
  - [`decide`](.agents/skills/decide/SKILL.md) writes a record.

  They live in `.agents/skills/`; `.claude/skills/` points Claude Code to them.

## Commands

Every command is a Docker command, the same in PowerShell, cmd and POSIX shells. What each gate runs, and how long it takes, is in [`docs/gates.md`](docs/gates.md); each backend's set-up and measurements are in [`docs/backends.md`](docs/backends.md).
- `docker compose up -d --wait python-fastapi` starts the Python backend on `127.0.0.1:8001`, and `go-nethttp` the Go backend on `net/http` on `127.0.0.1:8002`; `docker compose down` stops everything.
- `docker compose run --rm contract-checks` lints the contract's OpenAPI file.
- `docker compose run --rm python-fastapi-checks` runs the Python backend's gates: ruff, ruff format, `mypy --strict`, and pytest with 90% coverage.
- `docker compose run --rm go-checks` runs the Go backends' gates: golangci-lint, then `go test -race` with 90% coverage.
- `docker compose run --rm bench-checks` runs the evaluation tool's gates, the same as the Python backend's.
- `docker compose run --rm python-lock <folder>`, such as `bench`, rewrites a Python project's `uv.lock` after its dependencies change. Rebuild its checks afterwards, with `docker compose build <name>-checks`.

## Conventions

- **English everywhere:** code, notes, records.
- **Resources are stated, not assumed.** Each step says what it needs: memory, disk, time and money. Each measurement names the machine it ran on.
- **Pin dependencies to exact versions,** with a lockfile.
- **Nothing large in git.** Models, datasets and checkpoints stay out of it. Report disk use after a step that writes data.
- **No money is spent without a record:** hardware, rented compute and paid APIs.
- **One contract for every backend,** in [`contract/`](contract/README.md) ([0003](spec/decisions/0003-every-backend-implements-ai-bootstraps-chat-api.md), [0010](spec/decisions/0010-the-contract-ai-bootstraps-chat-in-text-paced-fakes-and-openapi-3-2.md)). A change to it changes every backend and the conformance suite in the same commit.
- **Fair by construction:**
  - every backend is written as a competent engineer would, following its ecosystem's documented production set-up;
  - none is tuned alone;
  - all run under the same limits.

  The exact rules arrive in plan step 3.1 ([0008](spec/decisions/0008-run-anywhere-with-docker-and-record-the-machine.md)).
- **The upstream is a setting,** the same for every backend, never a code path of its own ([0004](spec/decisions/0004-three-local-upstreams-llama-cpp-a-fake-server-and-an-in-process-fake.md)).
- **Every helper is measured alone first,** to show it isn't the bottleneck: the fake server, the network emulator, PostgreSQL and the load generator ([0004](spec/decisions/0004-three-local-upstreams-llama-cpp-a-fake-server-and-an-in-process-fake.md)).
- **Measurements:**
  - a run's results are written once, with a timestamp, and never edited;
  - every number in a doc names its run, its upstream and its machine;
  - numbers from different machines are never compared ([0008](spec/decisions/0008-run-anywhere-with-docker-and-record-the-machine.md)).
- **Runs anywhere with Docker** ([0008](spec/decisions/0008-run-anywhere-with-docker-and-record-the-machine.md)):
  - commands are Docker commands, the same in PowerShell, cmd and POSIX shells;
  - settings come from environment variables with working defaults, each in `.env.example`;
  - ports are published on `127.0.0.1` only.
- **Public** ([0009](spec/decisions/0009-publish-as-a-public-github-repository.md)):
  - keys stay in `.env`, never in git;
  - links to the owner's other projects point to their public repositories, never to a local folder.
