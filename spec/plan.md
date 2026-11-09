# Plan

The work, as small steps in order. Each step names the decision records it depends on or will create; see the [decision index](decisions/README.md). Each step ends in a few small commits.

**How we work through it**
- One step at a time. Before a step with design choices, the agent lays out the options, the evidence and a recommendation; the owner picks.
- A new decision gets its record first, in its own commit. A Proposed record becomes Accepted in the commit that implements it.
- Guesses go into the matching record's "Assumptions to verify", ticked with evidence once checked.
- Tick the step here in the commit that finishes it.

**What a step leaves behind.** A step that measures something writes down the number, the command that produced it, and the settings and machine it ran on, in `docs/`. A number that lives only in a terminal is lost.

**A thin slice first.** Phase 1 runs Python and Go against their in-process fakes, measured end to end with one workload, before the upstreams, the workloads and the database grow. The sibling projects started the same way.

## Phase 0: The spec

- [x] 0.1 The product spec, the requirements, this plan and the first records ([0001](decisions/0001-work-from-a-spec-and-record-every-decision.md) to [0009](decisions/0009-publish-as-a-public-github-repository.md)). Also a first pass of the notes, from the prior art, the load tools and the upstreams' documentation ([`docs/benchmarking.md`](../docs/benchmarking.md))
- [x] 0.2 The owner reviews the spec, the records and the notes, and picks the name and the licence. The first commit, and the public GitHub repository

## Phase 1: A thin slice

- [x] 1.1 **The contract.** ai-bootstrap's chat, written down as the one API every backend implements: the endpoints, the body, the stream's events and the errors. Also the fakes' behaviour: which tokens, the time to the first, the gap between them, and the settings that change them ([0003](decisions/0003-every-backend-implements-ai-bootstraps-chat-api.md), [0004](decisions/0004-three-local-upstreams-llama-cpp-a-fake-server-and-an-in-process-fake.md)). *Picked* ([0010](decisions/0010-the-contract-ai-bootstraps-chat-in-text-paced-fakes-and-openapi-3-2.md)): ai-bootstrap's chat cut to text, with its `reasoning` events and free `parameters`; both fakes paced from one token file; OpenAPI 3.2 and a page, in [`contract/`](../contract/README.md).
- [x] 1.2 **The repository's layout and the gates.** Where each backend, the evaluation tool and the fake server live, beside `contract/`; one Compose file, with the contract's settings in `.env.example`; each language's gates in Docker, and a lint of `contract/openapi.yaml`, falling back to OpenAPI 3.1 if no linter takes 3.2 ([0008](decisions/0008-run-anywhere-with-docker-and-record-the-machine.md), [0010](decisions/0010-the-contract-ai-bootstraps-chat-in-text-paced-fakes-and-openapi-3-2.md)). *Picked:* the layout by role ([0011](decisions/0011-lay-the-repository-out-by-role.md)); the evaluation tool in Python, apart from the load generator ([0012](decisions/0012-write-the-evaluation-tool-in-python-apart-from-the-load-generator.md)); gates equally strict, golangci-lint for Go ([0013](decisions/0013-gates-equally-strict-for-every-language.md)). OpenAPI 3.2 lints, so no fallback to 3.1.
- [x] 1.3 **The Python backend:** FastAPI, chat whole and streamed, readiness, errors, and the in-process fake. *Picked* ([0014](decisions/0014-the-python-backend-fresh-from-the-contract-on-uvicorn-standard-and-fastapis-sse.md)): written fresh from the contract with ai-bootstrap's pieces that fit, on `uvicorn[standard]` and FastAPI's own SSE.
- [ ] 1.4 **The Go backend:** the same API and fake, in `backends/go/`, renamed after its framework. *Choice:* the standard library's `net/http`, or a framework such as chi, Gin, Echo or Fiber.
- [ ] 1.5 **The conformance suite:** every backend answers the same requests the same way, and its fake keeps the contract's pace, within a tolerance taken from a measurement of the machine's timers ([0015](decisions/0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)).
- [ ] 1.6 **The first runner:** one workload at a fixed arrival rate, open-loop; latency and errors; each run saved once as JSON, with the machine it ran on. The load generator is measured on its own first. *Choice:* an existing load tool, such as k6, vegeta, oha or wrk2, or a client of our own.
- [ ] 1.7 **CI:** each language's gates, and the conformance suite against the in-process fakes, on every push.
- [ ] 1.8 **The first numbers:** both backends, under the same limits, written down in `docs/` with the command, the settings and the machine.

## Phase 2: The local upstreams

- [ ] 2.1 **The fake upstream server:** shaped like llama.cpp's OpenAI-compatible chat API, streaming the contract's tokens at its pace. It's written once, and measured on its own to show it isn't the bottleneck ([0004](decisions/0004-three-local-upstreams-llama-cpp-a-fake-server-and-an-in-process-fake.md)). *Choices:* its language; how closely it imitates llama.cpp's chunks.
- [ ] 2.2 **Each backend's upstream client:** the OpenAI-compatible call, whole and streamed, with ai-bootstrap's error mapping. *Choice:* each ecosystem's OpenAI SDK, as ai-bootstrap uses, or its plain HTTP client.
- [ ] 2.3 **llama.cpp in Compose:** the pinned server image, one small model on CPU, and readiness. *Choices:* the model, and the server's slots.
- [ ] 2.4 **Runs against the three local upstreams,** and the time each backend adds over its upstream.

## Phase 3: Measuring

- [ ] 3.1 **Fairness:**
  - each backend's CPU and memory limits, and the load generator's cores;
  - warm-up, repeats, and the order the backends run in;
  - the rule for each ecosystem's documented production set-up, such as uvicorn's workers or Go's `GOMAXPROCS` in a container.
- [ ] 3.2 **The workloads:** whole and streamed requests at fixed rates; a ramp to the ceiling, by a written rule; many open streams at once.
- [ ] 3.3 **Stream behaviour:** the jitter a backend adds, whether it buffers, and how fast a client's leaving stops the upstream; how each is measured.
- [ ] 3.4 **Resources:** memory, CPU, image size and start-up time, and how they're sampled.
- [ ] 3.5 **The runner, complete:** every backend, upstream and workload, resumable, each run saved once with what it ran on.

## Phase 4: A remote upstream

- [ ] 4.1 **The imitation:** the fake server over HTTPS behind a network emulator, with the latency, jitter and bandwidth of a remote API ([0006](decisions/0006-a-remote-upstream-ollama-cloud-beside-a-local-imitation.md)). The emulator is measured on its own first. *Choices:* the emulator, such as Toxiproxy; and its settings, perhaps taken from Ollama Cloud's own timings.
- [ ] 4.2 **Ollama Cloud:** one free model, at low rates, with the backends interleaved and repeated; its limits checked on ollama.com first.
- [ ] 4.3 **The imitation's numbers beside Ollama Cloud's,** and what they agree on.

## Phase 5: Conversations

- [ ] 5.1 **The contract, extended:** ai-bootstrap's conversations in text, and one schema in plain SQL, shared by every backend ([0005](decisions/0005-conversations-on-postgresql-as-version-1s-last-backend-phase.md)). *Choices:* what of ai-bootstrap's conversations to keep; how the migrations run.
- [ ] 5.2 **PostgreSQL in Compose,** pinned and sized, measured on its own to show it isn't the bottleneck, and reset and seeded before each run.
- [ ] 5.3 **The Python and Go stores,** and the conformance suite extended. *Choices:* each language's driver, and whether to use an ORM.
- [ ] 5.4 **The conversation workloads:** the history's read before the first token, storing the turn after it, more streams than database connections, and listing conversations as a plain-database baseline.

## Phase 6: The web UI and the report

- [ ] 6.1 **The web UI:** the runs, one run, and the backends compared with charts; starting a run through the same runner, and staying quiet during it ([0007](decisions/0007-a-web-ui-that-runs-the-benchmark-and-shows-its-results.md)). *Choices:* its stack; how it starts a run.
- [ ] 6.2 **The first full run and the report:** every number with its run and its machine, run on two machines. The timing numbers come from native Linux ([0015](decisions/0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)).

## Next

After version 1, in an order picked then:
- **The `add-language` skill,** written from what Python and Go taught.
- **Rust, Java, JavaScript and C++,** one at a time.
- **More than one framework or runtime per language.**
- **The developer's side:** lines of code, dependencies, build time, what was hard.
- **The post,** on LinkedIn and X.
