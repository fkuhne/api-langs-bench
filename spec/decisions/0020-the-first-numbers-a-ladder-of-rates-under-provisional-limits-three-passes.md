# 0020. The first numbers: a ladder of rates under provisional limits, in three passes

- Status: Accepted
- Date: 2026-11-10

## Context

Plan step 1.8 writes down the first numbers: every backend, under the same limits (R5), with the command, the settings and the machine. The limits, the workloads and the repeats are Phase 3's to settle. This step needs enough of each to end the thin slice.

What a quick ladder of rates showed on 2026-11-09 and 2026-11-10, on the owner's M3 under Colima, 10 s a point, with nothing saved as a run ([runner](../../docs/runner.md#what-the-ladder-rests-on)):
- **At 100 requests a second, nothing separates the backends.** Python used 53% of one CPU and Go 31%, and each p50 was within 5 ms of the 240 ms due.
- **Higher rates do.** Python's one process reached 108% of a CPU at 1,500 a second, with a p50 of 392 ms. Go's `net/http` kept its pace at 8,000 a second, on 1.6 CPUs.
- **Without a limit the comparison isn't equal:** Go takes more than one CPU, and Python's one process can't.
- **Under a 1-CPU limit,** Go's `net/http` still kept 4,000 a second. Go 1.27.3 sets `GOMAXPROCS` to 2 there, against 4 without a limit (our run).
- **Two traps in the load generator's set-up** looked like a backend's errors:
  - **Open files.** The container's limit is 1,024. With 2,048 connections, oha failed 1,033 requests at every rate with "Too many open files". With the limit raised, none.
  - **Idle connections.** uvicorn closes a connection idle for 5 s, its default. With 2,048 connections at 250 a second, oha lost 717 of 3,750 requests on connections Python had closed. With 128 connections, or with keep-alive off, none. Go's server has no idle timeout, so only Python showed it.

## Decision

The first numbers are the `stream-20` workload at 100, 500, 1,000 and 2,000 requests a second, for each backend under the same provisional limits, in three passes. One command makes them: `docker compose run --rm runner`.

- **The limits,** provisional until plan step 3.1: each backend's container gets 1 CPU and 512 MiB, from the `BACKEND_CPUS` and `BACKEND_MEMORY` settings. They always apply, for the conformance suite too. Each run reads its backend's limits back from Docker and records them.
- **The ladder,** provisional until plan step 3.2: 100, 500, 1,000 and 2,000 requests a second, each for 30 s after a warm-up of 5 s at the same rate. `--rate` gives others.
- **The connections** are sized to the rate: four times the streams open at once, so 96 at 100 a second and 1,920 at 2,000. Keep-alive stays on. Every connection is then reused within about a second, and no server's idle timeout comes into play. The runner's container may open 65,536 files.
- **Three passes,** from `--passes`. Each pass runs every backend, and the order rotates from one pass to the next, so no backend always runs first. The notes give each number's median over the passes, and its range.
- **A fresh backend for every run:** its container is made again, so no run inherits another's state.
- **A run's file** gains its pass, its backend's limits, and its rate in its name: `runs/<timestamp>-<backend>-<rate>rps.json`. Its `schema` becomes 2.
- **At the end, the runner prints a table** of its runs, in Markdown: for each backend and rate, the p50 and p99 with their ranges, the errors, and how many runs kept their rate.
- **The numbers come from the machine the owner names.** From a Mac they're development numbers, and say so ([0015](0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)).

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| No limits, and say so | Go would get 1.6 CPUs to Python's one |
| Plan step 3.1 first, for the real limits | It reorders the plan and delays the thin slice's end |
| The one rate, 100 a second | Three rows that barely differ |
| A new connection for every request | Every request pays for a TCP handshake, which a proxy in front of a real backend wouldn't |
| Many connections at every rate | Python's errors would come from its 5 s idle timeout, measured by accident. Whether to measure that default on purpose is plan step 3.1's question |
| One pass | No way to tell a difference from noise |

## Consequences

- **A queue can form in the load generator.** If a backend slows until every connection is busy, further requests wait in oha. The correction counts that wait, and a run says when its rate wasn't kept ([0018](0018-the-first-runner-oha-as-the-load-generator-one-streamed-workload-and-runs-committed-as-json.md)). So a backend never has more streams open than the connections allow: four times what its pace needs.
- Three passes of three backends at four rates are 36 runs: about 25 minutes (computed), and about 200 kB in git.
- Plan step 3.1 decides the real limits, whether the load generator gets its own cores, and whether a server's idle timeout is measured on purpose. Plan step 3.2 decides the real rates and the rule for the ceiling.
- The first three runs, of plan step 1.6, stay as they are, with `schema` 1 and no limits.

## Assumptions to verify

- [x] Go sizes itself to a container's CPU limit. *2026-11-10: under `--cpus 1`, Go 1.27.3 sets `GOMAXPROCS` to 2, its minimum, against 4 without a limit (our run).*
- [ ] Python's uvicorn, with one process, needs no setting to respect a 1-CPU limit. Unchecked: one process on one event loop can't use more than one CPU anyway.
- [x] With connections at four times the streams open at once, no request waits for a connection while a backend keeps its pace. To check in this step. *2026-11-10: both Go servers kept every rate to 2,000 a second with a p50 within 2.2 ms of the due time, and no error ([runner](../../docs/runner.md#a-check-of-the-ladder-on-2026-11-10)).*
- [x] Three passes give a range small enough to tell the backends apart. To check with the first numbers. *2026-11-10: partly. Python's ranges never touch Go's: at 100 a second its p50 was 243.0 to 243.3 ms against 240.9 to 241.0 ms. The two Go servers' ranges overlap wherever one pass was disturbed, and one stretch of pass 1 was: at 2,000 a second `net/http`'s p99 ranged from 243.2 to 2,081.5 ms, across Gin's 298.6 to 412.9 ms. Three passes give a median that survives one disturbed run, not a range that does ([runner](../../docs/runner.md#the-first-numbers-on-2026-11-10-on-a-core-i7-12850hx)).*
- [ ] The disturbed stretch of the first numbers' pass 1 came from the machine, not from `net/http`. Unchecked: a run doesn't record the backend's CPU or the machine's load yet (plan step 3.4).
- [ ] 512 MiB binds no backend at these rates. Peaks were near 105 MiB in the quick ladder; to check with the first numbers, once memory is sampled (plan step 3.4).

## Learned while building it

- **Under 1 CPU, Python ran out between 500 and 1,000 requests a second** on the Mac: at 1,000 it answered 695 a second. In the quick ladder, without a limit, it was near its ceiling at 1,500. One pass on a busy machine; the first numbers will say more ([runner](../../docs/runner.md#a-check-of-the-ladder-on-2026-11-10)).
- **A run that fails needs reading with care:** its percentiles leave out requests never sent, and cover only what oha timed. The table's last three columns say when that happened.

## Learned from the first numbers

On 2026-11-10, on the owner's Core i7-12850HX with Docker Desktop on Windows ([runner](../../docs/runner.md#the-first-numbers-on-2026-11-10-on-a-core-i7-12850hx)):
- **The 36 runs started within 24 min 31 s,** and take 197,511 bytes in git: as computed.
- **The ladder's steps are too wide for Python there.** It kept 100 a second, and answered about 300 a second at 500 and at 1,000. Plan step 3.2's rates need points between 100 and 500.
- **Every run says `"dirty": true`,** most likely from Windows line endings ([0018](0018-the-first-runner-oha-as-the-load-generator-one-streamed-workload-and-runs-committed-as-json.md)).

## Sources

- Our runs on 2026-11-09 and 2026-11-10 ([runner](../../docs/runner.md#what-the-ladder-rests-on)).
- uvicorn 0.54.0's default `timeout_keep_alive`, 5, read from its `Config` on 2026-11-10; the Go backends' `http.Server` in [`app.go`](../../backends/go/internal/app/app.go), which sets no idle timeout.
- The first numbers' 36 runs, 2026-11-10 ([runner](../../docs/runner.md#the-first-numbers-on-2026-11-10-on-a-core-i7-12850hx)).
- The owner's picks, 2026-11-10.
