# api-langs-bench

[![CI](https://github.com/fkuhne/api-langs-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/fkuhne/api-langs-bench/actions/workflows/ci.yml)

The same AI backend, written in several programming languages and measured on the same machine. Every backend serves one chat API, whole and streamed, in front of an LLM. An evaluation tool sends every backend the same load and records what it does:
- latency, and the time to the first token;
- how it passes the stream on;
- throughput, and where it breaks;
- memory and CPU.

Python and Go come first; Rust, Java, JavaScript and C++ follow. Fakes stand in for the LLM where its seconds would hide the backend's own cost.

**Status:** starting. The spec and the contract every backend implements are written, and each part's gates run in Docker ([`docs/gates.md`](docs/gates.md)). The Python backend and two Go backends, on `net/http` and on Gin, serve it ([`docs/backends.md`](docs/backends.md)); a conformance suite checks all three against it ([`docs/conformance.md`](docs/conformance.md)). A first runner sends one workload to each backend and saves each run in [`runs/`](runs/README.md) ([`docs/runner.md`](docs/runner.md)). CI runs the gates and the suite on every push ([`docs/gates.md`](docs/gates.md#in-ci)). The first numbers come next, from one command on the machine that will make them ([how](docs/runner.md#the-first-numbers)).

## Where to start

- [`docs/benchmarking.md`](docs/benchmarking.md): the notes on benchmarking an AI backend: prior art, metrics, load tools and the upstreams, each claim with its source.
- [`spec/product.md`](spec/product.md): what this project covers and what it doesn't.
- [`contract/`](contract/README.md): the one API every backend implements, and how the fakes behave.
- [`spec/plan.md`](spec/plan.md): the steps, in order. The next one is the first unticked.
- [`spec/decisions/`](spec/decisions/README.md): why each choice was made.

## How it's worked on

From a spec, one plan step at a time, with a record for each decision, the same way as the owner's other projects. [`AGENTS.md`](AGENTS.md) gives the method to coding agents.

## Licence

MIT No Attribution: copy any part freely, no notice needed ([`LICENSE`](LICENSE)).
