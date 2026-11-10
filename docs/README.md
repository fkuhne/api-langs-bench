# A guide to the notes

These pages say what was built, how it works, and what was measured. Every number names the command that made it, its settings and its machine. This page says which page to read for what, and explains the words the others use.

## The picture, in one minute

An AI backend sits between an app and a language model. The app sends it a chat request. The backend asks the model, and passes the answer back: all at once, or piece by piece as the model writes it.

```text
the load generator  ──▶  a backend  ──▶  its upstream
(plays many apps)        (Python, Go…)   (the model, or a fake of it)
```

This project builds that backend in several programming languages, sends each the same load, and measures what each does. A real model takes seconds to answer, and a backend adds milliseconds, so behind a real model every language looks the same. Most runs therefore put a **fake** in the model's place: it answers with fixed text on a known timetable, such as the first piece at 50 ms and one more every 10 ms. Whatever a run measures beyond that timetable is the backend's own.

## Which page to read

| To learn | Read |
|---|---|
| What a backend must do: its endpoints, its answers, its errors, and how the fakes behave | [The contract](../contract/README.md) |
| How each backend is set up, and what it weighs: its image, its start-up, its idle memory | [The backends](backends.md) |
| How we know every backend does the same work | [The conformance suite](conformance.md) |
| How a measurement is made, and the numbers so far | [The runner](runner.md) |
| What stands in for the model when a backend calls out over HTTP | [The fake upstream server](fake-server.md) |
| How to put a real model behind a backend | [llama.cpp](llama-cpp.md) |
| What keeps the code honest: lint, types, tests and coverage, locally and in CI | [The gates](gates.md) |
| What others have measured, how latency is measured without fooling yourself, and what we read about each tool | [Benchmarking an AI backend: notes](benchmarking.md) |
| What the project covers, and what it leaves out | [The product spec](../spec/product.md) |
| What's done and what's next | [The plan](../spec/plan.md) |
| Why each choice was made | [The decision records](../spec/decisions/README.md) |

New here? Read the contract's first three sections, then the runner's page.

## The words used here

### The parts

- **Backend.** The program being measured: an HTTP server that takes a chat request, asks its upstream, and returns the answer. There are three so far: Python on FastAPI, Go on `net/http`, and Go on Gin.
- **Upstream.** Whatever the backend asks for the answer. In production that's a language model's server. Here it's one of several, picked by a setting: a fake inside the backend, the fake server, llama.cpp, or a remote API.
- **Upstream client.** The part of a backend that calls its upstream: it opens the connection, sends the request, reads the answer's pieces as they arrive, and turns failures into the backend's own errors. It's code inside the backend, not a separate program. Each language writes it with its own HTTP library, so it's a large part of what the benchmark compares.
- **LLM.** A large language model, such as the one llama.cpp serves.
- **Token.** One piece of the answer's text, often a word or part of one. A model writes its answer a token at a time.
- **The contract.** The written description of the one API every backend implements, in [`contract/`](../contract/README.md). If two backends differed in what they do, their numbers couldn't be compared.
- **Fake.** A stand-in for the model. It answers with the same 175 tokens every time, on a timetable its settings give. There are two:
  - **the in-process fake** lives inside each backend. No network call is made, so it measures how a language serves HTTP alone;
  - **the fake server** is a separate program that answers the way llama.cpp's server does. A backend calls it over HTTP with its upstream client, so that client's cost is measured too.
- **llama.cpp.** An open-source program that runs language models. Its server speaks the same HTTP API as OpenAI's, which many tools call "OpenAI-compatible".
- **Helper.** Anything in a run that isn't the backend: the load generator, the fake server, a database. Each is measured alone first, to show the backend is what a run measures.

### The answers

- **Whole answer.** The complete answer in one HTTP response, once the model has finished.
- **Stream.** The answer sent piece by piece, each token as soon as it exists. Chat apps use it so text appears while the model is still writing.
- **Server-sent events (SSE).** The web's standard format for such a stream: lines of text over one long HTTP response, with a blank line after each event.
- **Chunk.** One piece of an upstream's stream. llama.cpp sends one chunk for each token.

### Timing

- **Pace.** A fake's timetable: when each token is due. With the first token at 50 ms and a gap of 10 ms, token 3 is due 80 ms after the request arrived.
- **Lateness.** How long after its due time something arrived. A fake's token that was due at 80 ms and arrived at 81.2 ms is 1.2 ms late. Lateness is how a backend's added time is seen.
- **Latency.** How long a request took, from when it was sent, or was due to be sent, until its answer ended.
- **p50, p95, p99.** Percentiles of many requests' latency. The p50, or median, is what half of the requests beat. The p99 is what 99 in 100 beat: it shows the slow tail that an average hides.
- **Time to first token.** How long until the first piece of the answer arrives. It's what a person watching a chat app feels first.
- **Timer error.** How late a machine wakes a program that asked to sleep until a given time. A paced fake depends on it, so each run measures it first. Docker on a Mac wakes about 2 ms late; Linux wakes within 0.2 ms.

### Measuring

- **Load generator.** The program that plays many clients at once. Here it's [oha](https://github.com/hatoo/oha).
- **Workload.** What's sent: which request, how fast, and for how long. The first one, `stream-20`, asks for a stream of 20 tokens.
- **Rate.** How many requests a second the load generator starts.
- **Open-loop.** The load generator starts requests at the set rate whatever the backend does, as real users would. A **closed-loop** tool waits for one answer before it sends the next request, so a slow backend receives less load and looks better than it is. That flaw is called **coordinated omission**.
- **Run.** One workload sent to one backend at one rate, once. Each run is saved in one file in [`runs/`](../runs/README.md), and never edited.
- **Pass.** One round of runs: every backend at every rate. Several passes show how much a number moves from one run to the next.
- **Kept the rate.** The load generator managed to send at least 99% of the requests it was due to send. When a backend falls behind, requests queue up, and a run that didn't keep its rate has numbers that need careful reading.
- **Ceiling.** The highest rate a backend, or a helper, still keeps.
- **Limits.** The CPU and memory each backend's container may use: the same for every backend, 1 CPU and 512 MiB for now.

### Checking

- **Conformance suite.** The checks that every backend answers the same requests the same way, and that each fake keeps its pace.
- **Gate.** A check a change must pass before it's kept: a linter, a type checker, the tests, and a coverage minimum.
- **CI.** The same gates and the conformance suite, run by GitHub on every push.
- **Decision record.** One file for each choice that shaped the project: what was chosen, what wasn't, and what's still to verify. Cited by number, such as 0017.
- **R1, R4 and the like.** The requirements, numbered, in [`spec/requirements.md`](../spec/requirements.md).
- **Plan step.** One unit of work in [`spec/plan.md`](../spec/plan.md), such as 2.1.
