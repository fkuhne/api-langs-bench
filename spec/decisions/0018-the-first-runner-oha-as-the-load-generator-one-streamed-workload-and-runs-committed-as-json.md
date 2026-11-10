# 0018. The first runner: oha as the load generator, one streamed workload, and runs committed as JSON

- Status: Accepted
- Date: 2026-11-09

## Context

Plan step 1.6 builds the first runner: one workload at a fixed arrival rate, open-loop; latency and errors; each run saved once as JSON, with the machine it ran on (R7, R14). The load generator is a separate program ([0012](0012-write-the-evaluation-tool-in-python-apart-from-the-load-generator.md)), and is measured on its own first (R4).

What was checked on 2026-11-09:

| Tool | Latest release | Open-loop | Times each event of a stream |
|---|---|---|---|
| oha (Rust) | 1.16.0, 2026-08-23 | `-q` sets the rate, and `--latency-correction` corrects for coordinated omission (its `--help`) | No: the whole response, and the first byte |
| k6 (Go, scripted in JavaScript) | 2.3.0, 2026-09-21 | Its arrival-rate executors | Only through xk6-sse, a third-party extension, with the time taken in JavaScript |
| vegeta (Go) | 12.13.0, 2025-10-31 | Yes | No: its latency is the whole body's read |
| wrk2 (C) | None; last push 2024-03-03 | Yes | No |

- **oha against `go-nethttp`,** from a container on Compose's network, on the owner's M3 under Colima:
  - without a rate, it sent 163,411 requests a second to `/api/health`, over 50 connections for 5 s, all answered;
  - at 500 streams a second of 20 tokens each, for 5 s, it sent 499.8 a second, and all 2,500 answered 200.
- **oha's JSON** holds a summary, percentiles of the latency and of the time to the first byte, a histogram, and counts by status and by error. It holds no per-request times; `--db-url` writes those to SQLite.
- **No existing tool gives the time to the first token or the gaps between tokens** without code of our own. Those are plan steps 2.4 and 3.3.

## Decision

The first runner is `docker compose run --rm runner`, in Python, in `bench/`. It sends one streamed workload to each backend in turn with oha 1.16.0, and saves each run once as `runs/<timestamp>-<backend>.json`, committed to git.

- **The load generator is oha 1.16.0,** its binary copied into the runner's image, and run by the runner on Compose's network. It runs with:
  - `-q`, the rate, and `--latency-correction`, so a request's latency counts from when it was due to be sent;
  - `-z`, the duration, and `-w`, so requests open at the end are waited for, not cut;
  - `-t 30s`, so a request with no answer after 30 s counts as an error;
  - `--output-format json`.
- **What reads each event of a stream** is decided at plan step 3.3, which needs it. A client of our own can then be checked against oha.
- **The one workload,** named `stream-20`:
  - `POST /api/chat/stream`, with `max_tokens` 20;
  - the fake paced: the first token at 50 ms, then one every 10 ms, so each stream is due to end at 240 ms, and about 24 are open at once;
  - 100 requests a second for 30 s, after a warm-up of 5 s at the same rate, which isn't counted;
  - 256 connections, about ten times what the rate needs, so the connections never hold a request back.

  The rate is provisional. Plan step 3.2 sets the real workloads.
- **One backend at a time.** The runner stops the other backends, starts the one it measures with the workload's settings, and waits until it's ready. At the end, it leaves every backend running with the settings `.env` gives, as the conformance suite does ([0017](0017-the-conformance-suite-pytest-that-drives-compose-and-a-pace-rule-from-the-machines-timers.md)).
- **A run's file** holds:
  - **what ran:** the backend, its image's ID, the upstream, the workload with its settings, and oha's command;
  - **what it ran on:** the repository's commit, and whether tracked files had changed; oha's, Docker's and Compose's versions; Docker's own account of its machine; the owner's description of the host, from the `BENCH_MACHINE` setting; and the machine's timer error, probed before the run ([0015](0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md));
  - **what was measured:** the requests sent, the rate reached, the latency's p50, p95 and p99, the counts by status and by error, and oha's whole summary.
- **Written once.** The file is created, never opened again. Its name carries the time in UTC and the backend.
- **Committed.** A run is a few kilobytes. A run a doc cites is committed with that doc. Others may be deleted before they're committed, never edited.
- **The repository's commit** is read with dulwich 1.2.21, a Git library in Python, pinned in the lockfile like every dependency. The repository is mounted read-only.
- **oha is measured alone first,** and the notes say how:
  - its ceiling, against the fastest endpoint we have;
  - its latency against the paced fake, whose time is known;
  - that its correction counts a request's wait when the connections run out.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| A load client of our own, now | One tool for everything, with exact arrival times and each event's time. But much more to build and prove before the first number, and its language would be a contestant's, such as Go or Rust, or too slow, such as Python |
| k6 with xk6-sse | One tool, with scripted scenarios. But it depends on a third-party extension, and timing in JavaScript adds a cost nobody has measured |
| vegeta | In Go, a contestant's language, and no more than oha gives |
| wrk2 | No release, and no push since March 2024 |
| A whole-answer workload | Simpler, but it skips the stream, which the project is about |
| Both workloads, one after the other | Twice the time, and closer to plan step 3.2's job |
| `runs/` ignored by git | Nothing grows, but a doc would cite files readers can't open |

## Consequences

- The first numbers (plan step 1.8) come from this runner.
- The runner trusts oha's percentiles. They're checked once against per-request times, in this step.
- A second tool, or a client of our own, arrives at plan step 3.3 for each event's time.
- When Rust becomes a contestant, the load generator shares its language. Revisit then.
- The repository grows by a few kilobytes for each run kept.
- The limits each backend runs under, and the load generator's cores, are still plan step 3.1's. Until then a run's numbers are for development.

## Assumptions to verify

- [x] oha's ceiling is well beyond the workload's rate on the machine that runs it. To check in this step. *2026-11-09: 163,411 requests a second against `go-nethttp`'s liveness, 1,600 times the rate ([runner](../../docs/runner.md#the-load-generator-measured-alone)).*
- [x] oha's latency against the paced fake agrees with the conformance suite's own client, within the machine's timer error. To check in this step. *2026-11-09: oha saw streams due at 240 ms end 1.3 ms late at the median; the suite's client saw 4.1 to 5.0 ms, one stream at a time. Under load, the VM's timers are tighter ([runner](../../docs/runner.md#the-load-generator-measured-alone)).*
- [x] With `--latency-correction`, a request that waits for a free connection has its wait counted. To check in this step, with too few connections on purpose. *2026-11-09: with 10 connections, the p50 was 3,207.7 ms corrected and 241.3 ms not. But requests still due when the time ends are never sent, so a run records whether its rate was kept ([runner](../../docs/runner.md#the-load-generator-measured-alone)).*
- [x] oha's percentiles match the per-request times it writes with `--db-url`. To check in this step. *2026-11-09: the p50 is the same to the microsecond; the p95 and p99 are within 0.06 ms ([runner](../../docs/runner.md#the-load-generator-measured-alone)).*
- [x] oha sends its requests evenly, not in bursts each second. To check in this step, from the per-request times. *2026-11-09: partly. The gap between due times was 9.98 ms at the median, but from 0.001 to 27.5 ms on this Mac: when oha's own timer wakes late, the next requests are due late, then close together ([runner](../../docs/runner.md#the-load-generator-measured-alone)).*
- [ ] On native Linux, oha's due times keep an even gap. To check on the report's machine (plan step 6.2).
- [ ] oha's time to the first byte is the body's first byte, so the first token of a stream. The numbers say so; to check in oha's code at plan step 2.4.
- [x] dulwich reads the commit, and whether tracked files changed, from a repository mounted read-only. To check in this step. *2026-11-09: it read the commit with `dirty` true while files were changed, and false in the first runs, made from a clean tree with new runs untracked ([runner](../../docs/runner.md#the-first-runs-on-2026-11-09)).*
- [ ] `dirty` means the same on a Windows checkout. *2026-11-10: it doesn't yet. All 36 of the first numbers' runs say true. Reproduced on the Mac; on that machine the tree is clean and `core.autocrlf` is `true` (the owner, 2026-11-10), but the file that sets it wasn't reported: a clone checked out with CRLF line endings, by a `core.autocrlf` set outside the repository as Git for Windows sets it, read as dirty in 180 of 183 tracked files; with the setting in the clone's own config, or with LF endings, it read as clean ([runner](../../docs/runner.md#why-every-file-says-dirty)). To decide: a `.gitattributes` that keeps LF endings everywhere.*

## Sources

- GitHub's API for each tool's latest release and last push, 2026-11-09.
- oha 1.16.0's `--help` and JSON output, and our runs of it against `go-nethttp`, 2026-11-09.
- Search summaries on k6's and vegeta's handling of streams, 2026-11-09: [xk6-sse's package page](https://beta.pkg.go.dev/github.com/phymbert/xk6-sse), and [a mirror of vegeta's documentation](https://docsearch.algolia.com/mcp/docs/repo/tsenart/vegeta).
- Our runs on 2026-11-09 ([runner](../../docs/runner.md)).
- The owner's picks, 2026-11-09.
