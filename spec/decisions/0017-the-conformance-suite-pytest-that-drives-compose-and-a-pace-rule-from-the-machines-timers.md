# 0017. The conformance suite: pytest that drives Compose, and a pace rule from the machine's timers

- Status: Accepted
- Date: 2026-11-09

## Context

Plan step 1.5 builds the conformance suite. It checks that every backend answers the same requests the same way (R1), and that its fake keeps the contract's pace (R3), "within a tolerance taken from a measurement of the machine's timers" ([0015](0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)). It's part of the evaluation tool, in Python ([0012](0012-write-the-evaluation-tool-in-python-apart-from-the-load-generator.md)). For now it checks three backends: FastAPI, `net/http` and Gin.

Some checks need a backend started with other settings: the reasoning, the pace, and a backend's refusal to start with an invalid value ([contract](../../contract/README.md#settings)).

What we knew on 2026-11-09:
- **Compose works from a container.** A container holding Docker's socket, on `docker:29.5.2-cli`, restarted `go-nethttp` with new settings in 2.1 s. With `FAKE_ANSWER_TOKENS=0`, `go-gin` exited with code 1 and logged why.
- **The Docker command-line tools:** `docker:29.5.2-cli` holds Docker 29.5.2 (38.3 MiB) and Compose 5.1.4 (29.4 MiB).
- **Schemathesis 4.11.0** validates OpenAPI 3.2's `itemSchema` for server-sent events ([its guide](https://schemathesis.readthedocs.io/en/stable/guides/server-sent-events/)). It checks the schema, not the tokens, their order or their pace.
- **This Mac's timers,** in Docker's VM ([0015](0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md), [backends](../../docs/backends.md#timers-in-dockers-vm-on-this-mac)):
  - a 20 ms sleep wakes 4.4 ms late at the median, 6.4 ms at the p99;
  - every backend's first token, due at 100 ms, came at 108 to 117 ms;
  - single tokens came up to 33 ms late.

## Decision

The conformance suite is a pytest suite in `bench/conformance/`, run with `docker compose run --rm conformance`. It drives Compose itself over Docker's socket, to start each backend with each set of settings it needs. Its pace rule has three checks, with a tolerance measured at the start of every run.

- **The command:** `docker compose run --rm conformance`. pytest's own options may follow, such as `-k go-gin`.
  - Compose starts the three backends first, building any image that's missing. After a backend's code changes, `docker compose build` rebuilds it.
  - At the end, the suite leaves each backend running with the settings `.env` gives.
- **The settings.** The suite restarts a backend with `docker compose up -d --wait --no-build --no-deps <service>`. It sets every setting itself, so a `.env` doesn't change what's checked. It uses three sets:
  - **the defaults:** the contract's, with 256 answer tokens, so the answer wraps past the 175th;
  - **paced, with reasoning:** the first token at 100 ms, then one every 20 ms; 2 reasoning tokens, then 40 answer tokens;
  - **invalid:** a value below its minimum, a value that isn't a number, and an unknown upstream. Each must stop the start-up.
- **Docker's socket** is mounted into the suite's container. The repository is mounted read-only, so the suite's Compose reads `compose.yaml` and `.env`. The socket gives root on Docker's host, as it does to any tool that drives Docker. The Docker and Compose binaries are copied from `docker:29.5.2-cli`.
- **What it checks,** for each backend:
  - **health:** liveness and readiness;
  - **the whole answer:** the contract's example, `max_tokens` (a whole number cuts the answer; `5.0`, `"5"`, `0` or a larger number don't), wrapping past the last token, and `prompt_tokens`, words split only on spaces, tabs, line feeds and carriage returns;
  - **the stream:** its headers, sent before the first token; its strict wire format; the events' order; every token's text against the token file; and `done` against the whole answer;
  - **the reasoning,** whole and streamed;
  - **errors:** each kind of invalid body, on both paths; each `fake_error` status, whole and streamed, with its tokens first; a malformed `fake_error`;
  - **the settings:** the three invalid ones;
  - **the pace,** by the rule below.
- **Compared by the contract's rules** ([contract](../../contract/README.md#comparing-answers)):
  - each body and each event is validated against the contract's schemas;
  - the expected answers come from the token file, through the suite's own model of the fakes;
  - that model is itself checked against the example on the contract's page.
- **The pace rule.** An event's lateness is when it arrives, after the request was sent, less its due time. Each paced stream must pass three checks:
  - **No event early,** by any amount. The backend starts after the request is sent, so an early event is always a bug.
  - **Lateness doesn't add up:** the median lateness of the stream's last quarter of events is within T of its first quarter's. A fake that sleeps one gap after each token fails it.
  - **The median lateness is within T.**
- **The tolerance T** is the p99 lateness of a timer probe, plus a margin. The probe runs at the start of every run, in the suite's container: 200 sleeps, each to a deadline 10 ms after the last one's. The margin is 10 ms, fixed from this step's runs: at 5 ms, the first run failed a correct backend, whose single events came 7 to 10 ms late at the median on this Mac ([conformance](../../docs/conformance.md#the-pace-rule)).
- **The whole answer and a failure** must come at their token's time, by the same rule. Each is a single event, so the suite takes the median of repeated requests.
- **The suite's own parts** live in `bench/bench/`, with unit tests under `bench-checks`: the stream's parser, the model of the fakes, the pace rule, and the Compose driver.
- **Not checked:**
  - **A client that leaves.** The in-process fake can't be seen from outside the backend. Each backend's own tests check it, and plan step 3.3 measures it against the fake server.
  - **Readiness answering 503,** since the in-process fake is always ready.
  - **The logs of a refused start-up,** which are each framework's own.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| Compose defines a copy of each backend for each set of settings | No socket, but two more services per backend: 6 now, 12 at six languages. No way to check a refused start-up |
| One set of settings, with the backends started by hand first | The reasoning and the defaults can't both be checked, and it takes two commands |
| A pace window on each event: every one within its due time plus T | One rule, the strictest, but flaky on this Mac: single tokens came 33 ms late |
| A fixed tolerance, such as 25 ms | Too loose on native Linux, and 0015 asks for a measured one |
| Schemathesis | It checks schemas, not tokens, order or pace. Its random `parameters`, and answers the contract doesn't list, such as 404 and 405, would need tuning. It could join the suite later |
| A checker of our own that writes a JSON report | More code than pytest for the same checks |

## Consequences

- One command checks every backend. A new backend adds its service to the suite's list and to the conformance service's `depends_on`.
- The runner (plan step 1.6) and the web UI (plan step 6.1) need the same control of Compose, and can reuse the driver.
- **A backend's service can't use a relative bind mount.** The suite's Compose resolves paths inside its own container, where the repository is at `/repo`, and the daemon would look for them on its own host.
- On this Mac, T is a few milliseconds wide, from the VM's timers. On native Linux, it's mostly the margin.
- [0012](0012-write-the-evaluation-tool-in-python-apart-from-the-load-generator.md)'s open assumption, that Python times each event closely enough, is checked in this step.

## Assumptions to verify

- [ ] Mounting `/var/run/docker.sock` works the same with Docker Desktop on macOS and on Windows. Unchecked; to check in CI (plan step 1.7) and on the report's second machine (plan step 6.2). *2026-11-10: it works on GitHub's Linux runner, with Docker 28.0.4 ([conformance](../../docs/conformance.md#in-ci-on-2026-11-10)). Docker Desktop is still unchecked.* *2026-11-10, later: on Docker Desktop for Windows (WSL 2), with Docker 29.7.2, the runner drove Compose through the socket for 36 runs ([runner](../../docs/runner.md#the-first-numbers-on-2026-11-10-on-a-core-i7-12850hx)). The suite's own run there isn't recorded, and Docker Desktop on macOS is still unchecked.*
- [x] The margin keeps a correct backend from failing: no false failure in 10 runs of the suite on this Mac. To check in this step. *2026-11-09: at 10 ms, 288 checks passed in 10 runs out of 10. At 5 ms, the first run failed the Python backend twice ([conformance](../../docs/conformance.md#measured-on-2026-11-09)).*
- [ ] The margin can shrink on native Linux, where timers are tighter. To check on the report's machine (plan step 6.2). *2026-11-10, in CI, a cloud VM: the probe's p99 was 0.09 to 0.14 ms, and the streams' median lateness 1.1 to 2.6 ms, so T, at 10.1 ms, is mostly margin. A fake that drifts would likely pass there ([conformance](../../docs/conformance.md#in-ci-on-2026-11-10)).*
- [x] A fake that sleeps one gap after each token fails the pace rule, on this Mac. To check in this step, with that fake planted on purpose. *2026-11-09: it fails on both Go servers, with a median lateness of 62.0 and 58.5 ms ([conformance](../../docs/conformance.md#measured-on-2026-11-09)).*
- [x] Each check fails when it should. To check in this step, with mistakes planted on purpose. *2026-11-09: six planted mistakes, each caught ([conformance](../../docs/conformance.md#measured-on-2026-11-09)). Not every check was given a mistake of its own.*

## Sources

- [Schemathesis 4.11.0's release](https://newreleases.io/project/pypi/schemathesis/release/4.11.0) and [its guide to server-sent events](https://schemathesis.readthedocs.io/en/stable/guides/server-sent-events/), read on 2026-11-09.
- Our runs on 2026-11-09: Compose from a container, and the size of `docker:29.5.2-cli`'s binaries.
- Our runs of the suite on 2026-11-09 ([conformance](../../docs/conformance.md)).
- The timer measurements in [0015](0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md) and [backends](../../docs/backends.md).
- The owner's picks, 2026-11-09.
