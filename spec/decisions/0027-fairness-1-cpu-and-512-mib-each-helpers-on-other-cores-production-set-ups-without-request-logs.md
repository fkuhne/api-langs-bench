# 0027. Fairness: 1 CPU and 512 MiB each, the helpers on other cores, and production set-ups without request logs

- Status: Proposed
- Date: 2026-11-16

## Context

Plan step 3.1 writes the fairness rules that earlier records left to it (R5, R6):
- each backend's limits, provisional at 1 CPU and 512 MiB since [0020](0020-the-first-numbers-a-ladder-of-rates-under-provisional-limits-three-passes.md), and where the load generator runs ([0008](0008-run-anywhere-with-docker-and-record-the-machine.md), [0018](0018-the-first-runner-oha-as-the-load-generator-one-streamed-workload-and-runs-committed-as-json.md));
- the rule for each ecosystem's production set-up: workers, the access log and other run-time settings ([0014](0014-the-python-backend-fresh-from-the-contract-on-uvicorn-standard-and-fastapis-sse.md), [0016](0016-two-go-backends-net-http-and-gin-in-one-module.md));
- warm-up, repeats and order ([0020](0020-the-first-numbers-a-ladder-of-rates-under-provisional-limits-three-passes.md));
- the upstream client's pool and how long it keeps idle connections ([0024](0024-each-backends-upstream-client-its-plain-http-client-one-pool-setting-no-retries.md));
- whether timed runs on Linux use the host's network ([0015](0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)).

Until now, each backend ran with its framework's defaults. Python ran one uvicorn process with its access log on, Gin ran `gin.Default()` with its logger, and `net/http` wrote no log. Each had 1 CPU of time and 512 MiB, and the load generator and the fake server shared the machine's cores with it.

What was read and run on 2026-11-16:
- **FastAPI's container guide** advises "a single Uvicorn process per container" when replication is handled outside it. It suggests `--workers` for "a single server", as with Docker Compose, and gives no rule for how many.
- **uvicorn 0.54.0** (`uvicorn --help`, in the backend's image): `--workers` "defaults to the $WEB_CONCURRENCY environment variable if available, or 1", and the access log is on unless `--no-access-log`. Its deployment page says nothing of containers or of the access log.
- **Go's runtime docs:** `GOMAXPROCS` defaults to the least of the logical CPUs, the CPU affinity mask and the cgroup's CPU quota, rounded up. "However, it will never set GOMAXPROCS less than 2 unless the logical CPU count or CPU affinity mask count are below 2." Under a 1-CPU quota it's 2 (our run, 2026-11-10).
- **Gin's docs:** `gin.Default()` attaches the Logger and Recovery middleware, and the Logger "will write the logs to gin.DefaultWriter even if you set with GIN_MODE=release", stdout by default.
- **Docker's docs:** `--cpus` is a CFS quota, checked every 100 ms; `--cpuset-cpus` limits the CPUs a container may use.
- **Compose** 5.5.1, and 5.1.4 inside the runner's image, take `cpuset` from a setting, and leave the container unpinned when the setting is empty (our run).
- **Sketches on the development Mac** (Docker in Colima's VM, 4 CPUs, a busy host; nothing saved in `runs/`; [backends](../../docs/backends.md#fairness-sketches-on-2026-11-16)):
  - with 1 CPU of time and nothing pinned, with 1 CPU of time on cores apart from the load generator's, and pinned to one core alone, the medians were the same: Go at 2,000 a second 241.9 to 242.7 ms, Python at 400 a second 243.4 to 243.6 ms. The p99s varied without a pattern;
  - Python used 2.10 and 2.28 ms of CPU per request with its access log, and 1.92 and 2.24 ms without: the log's cost didn't show above the noise.
- **The owner's runs** of 2026-11-16: where a backend kept up, its median moved by 0.1 ms at most from pass to pass, and one disturbed pass was outvoted by the other two ([runner](../../docs/runner.md#the-upstreams-numbers-on-2026-11-16-on-a-core-i7-12850hx)).

## Decision

Every backend runs with 1 CPU of time and 512 MiB, on cores of its own when the machine names them, in its ecosystem's documented production set-up, with one rule across them: one process per CPU of the limit, and no log line per request.

**The limits** (R5):
- **1 CPU and 512 MiB, final.** `BACKEND_CPUS` and `BACKEND_MEMORY` stay settings, for experiments; the report uses these values.
- **The CPU limit is a share of time,** `--cpus`, on every machine.
- **Cores of their own, when the machine names them.** `BACKEND_CPUSET` pins every backend to its cores. `HELPER_CPUSET` pins everything else that runs during a measurement: the runner and its load generator, the conformance suite, the fake server and llama.cpp. Both are empty by default, so nothing is pinned, and every machine can run it. On the report's machine both are set, without overlap. On a CPU with fast and slow cores, the backend's cores are fast ones.
- **Under Docker Desktop,** pinning holds within its VM, whose CPUs aren't the machine's cores, so it guarantees less there.
- **Each run records the cores:** the backend's and the fake server's as Docker holds them to them, and the load generator's from its own process.

**The production set-up rule** (R6):
- **Each backend follows its ecosystem's documented production set-up,** and its notes cite the documentation for each setting.
- **One process per CPU of the limit.** With 1 CPU, that's one uvicorn process, as FastAPI's container guide advises, and one Go process, with Go's default `GOMAXPROCS`: 2 under a 1-CPU quota, Go's floor. A larger limit would set uvicorn's workers to match, through `WEB_CONCURRENCY`.
- **No log line per request,** in any backend. uvicorn runs with `--no-access-log`, and Gin's router is `gin.New()` with Gin's Recovery alone; `net/http` writes none already. Warnings and errors are still logged. A line per request was work that two backends did and one didn't, and what a container prints is handled by Docker outside its CPU limit (unchecked).
- **Release modes on:** `GIN_MODE=release`, as before.
- **Nothing tuned beyond the documentation:** no setting for the garbage collector, buffers or threads that the documentation doesn't name for production.

**Kept as they were:**
- **Warm-up, repeats and order** ([0020](0020-the-first-numbers-a-ladder-of-rates-under-provisional-limits-three-passes.md), [0026](0026-runs-against-the-local-upstreams-the-upstream-alone-as-the-baseline.md)): a fresh container for each run, 5 s of warm-up at the same rate, 30 s measured, and 3 passes whose order rotates. The warm-up is looked at again when the first language that compiles while it runs arrives, such as Java or JavaScript.
- **The upstream pool** ([0024](0024-each-backends-upstream-client-its-plain-http-client-one-pool-setting-no-retries.md)): 1,000 connections, and each library's idle expiry, 5 s in httpx2 and 90 s in Go. At 2,000 a second, a backend that keeps up has about 480 streams open, and each connection is reused within a second, so neither expiry is reached in a steady run (computed).
- **Compose's network,** on every machine, timed runs included ([0015](0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)). The load generator reaches each backend by its service name, as every run's command shows, so Docker's address translation, which serves only the published ports, isn't on the path.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| 1 CPU of time, nothing pinned | The load generator and the fake server could share the backend's cores, which R5 rules out |
| Pinned cores alone, with no share of time | Go's `GOMAXPROCS` would follow the cores, not the limit, and every machine would need core numbers to run at all |
| 2 CPUs, with 2 Python processes | It shows how each backend uses a second core, but doubles the runs and the machine. It may come later, as a size of its own |
| Each framework's defaults | Two backends wrote a line per request and one didn't: unequal work |
| Every backend writing a line per request | Closer to many services, but part of its cost would fall outside the limit, in Docker's handling of the output (unchecked) |
| 5 passes | Narrower ranges, for about two hours a run. Three already outvote a disturbed pass |
| 15 s of warm-up | Ready for languages that compile while they run, for 20 more minutes now and no gain yet |
| No limit on the upstream pool | An overloaded backend would open connections without end |
| The host's network on Linux | Linux only, a port for each backend and a second Compose set-up, to remove a small cost that every backend pays alike |

## Consequences

- The Python and Gin backends change: no access log, and `gin.New()`. Their runs made before this record include a log line per request.
- Two new settings, `BACKEND_CPUSET` and `HELPER_CPUSET`, in `.env.example`. A run's file gains the cores (schema 4).
- The report's machine needs its cores chosen (plan step 6.2).
- [0014](0014-the-python-backend-fresh-from-the-contract-on-uvicorn-standard-and-fastapis-sse.md)'s and [0016](0016-two-go-backends-net-http-and-gin-in-one-module.md)'s "until plan step 3.1's rule" are answered, and [0020](0020-the-first-numbers-a-ladder-of-rates-under-provisional-limits-three-passes.md)'s limits are final.
- A size above 1 CPU, if it comes, sets `WEB_CONCURRENCY` to match.

## Assumptions to verify

- [ ] A log line per request costs a backend a measurable share of its CPU. On the Mac it didn't show above the noise; to measure with plan step 3.4's CPU sampling.
- [ ] Go's two threads under a 1-CPU quota aren't throttled enough to change its tail. On the Mac, the quota and a pinned core gave the same medians; plan step 3.4.
- [ ] What a container prints is handled outside its CPU limit. Unchecked.
- [ ] Compose 2.38.2, the one in CI, accepts an empty `cpuset`. To check in CI, in this step.
- [ ] 512 MiB binds no backend at these rates, as [0020](0020-the-first-numbers-a-ladder-of-rates-under-provisional-limits-three-passes.md) assumes. Plan step 3.4.

## Sources

- [FastAPI in Containers - Docker](https://fastapi.tiangolo.com/deployment/docker/), read on 2026-11-16: "One Process per Container" and "Containers with Multiple Processes and Special Cases".
- uvicorn 0.54.0's `--help`, in the Python backend's image, and [its deployment page](https://github.com/encode/uvicorn/blob/master/docs/deployment/index.md), read on 2026-11-16.
- [Go's `runtime` package](https://pkg.go.dev/runtime), "Default GOMAXPROCS", and [Go 1.25's release notes](https://go.dev/doc/go1.25), read on 2026-11-16.
- [Gin's documentation](https://github.com/gin-gonic/gin/blob/master/docs/doc.md), read on 2026-11-16.
- [Docker's resource constraints](https://docs.docker.com/engine/containers/resource_constraints/), read on 2026-11-16.
- Our runs on the Mac, 2026-11-16: Compose and `cpuset`, and the sketches ([backends](../../docs/backends.md#fairness-sketches-on-2026-11-16)).
- The owner's runs of 2026-11-16 ([runner](../../docs/runner.md#the-upstreams-numbers-on-2026-11-16-on-a-core-i7-12850hx)).
- The owner's picks, 2026-11-16.
