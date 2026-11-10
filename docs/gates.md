# The gates

Each part of the repository has gates: checks that fail on a mistake, run in Docker the same way on every machine, and in CI on every push ([below](#in-ci)). They're about equally strict for every language ([0013](../spec/decisions/0013-gates-equally-strict-for-every-language.md)). They check the code, not its speed.

A gate is one command that passes or fails. Nothing is installed on the machine but Docker: each gate's tools live in its image. The other pages are listed in [the guide](README.md).

## What runs

| Command | Checks | Versions |
|---|---|---|
| `docker compose run --rm contract-checks` | [`contract/openapi.yaml`](../contract/openapi.yaml), with Redocly's recommended rules except one ([`redocly.yaml`](../contract/redocly.yaml)) | Redocly CLI 2.69.0 |
| `docker compose run --rm python-fastapi-checks` | [`backends/python-fastapi/`](../backends/python-fastapi/): `ruff check` with 16 rule families, `ruff format --check`, `mypy --strict`, and pytest with branch coverage of at least 90% and warnings as errors | Python 3.14.8, uv 0.12.24, ruff 0.16.10, mypy 2.4.0, pytest 9.1.1, pytest-cov 7.1.0, as ai-bootstrap |
| `docker compose run --rm go-checks` | [`backends/go/`](../backends/go/): `golangci-lint run` ([`.golangci.yml`](../backends/go/.golangci.yml): the standard linters, plus gosec, bodyclose, noctx, errorlint and revive, with gofmt and goimports), then `go test -race -shuffle=on`, failing below 90% coverage. Coverage counts every package's lines run by any package's tests (`-coverpkg=./...`), as pytest-cov counts the Python backend's; the shared contract tests in `internal/apitest` run from each server's tests | Go 1.27.3, golangci-lint 2.15.0 |
| `docker compose run --rm fake-server-checks` | [`fake-server/`](../fake-server/): the Go backends' gates, with its own [`.golangci.yml`](../fake-server/.golangci.yml) | As the Go backends. No dependency beyond Go's standard library |
| `docker compose run --rm bench-checks` | [`bench/`](../bench/): the Python backend's gates | As the Python backend, plus jsonschema 4.26.0, PyYAML 6.0.3, referencing 0.37.0, httpx2 2.13.1 and dulwich 1.2.21 |

Each checks service mounts its folder and `contract/` read-only, so it checks the current files. Go's checks also keep Go's build cache and golangci-lint's in two named volumes, so a run compiles only what changed; `docker compose down --volumes` clears them. After a dependency changes:
- **Python:** `docker compose run --rm python-lock <folder>`, such as `bench`, rewrites the folder's `uv.lock`. Then `docker compose build <name>-checks`.
- **Go:** `docker compose run --rm go-mod tidy` rewrites `backends/go/`'s `go.mod` and `go.sum`, after a `require` line changes. Then `docker compose build go-checks`.

## Measured on 2026-11-06

**The machine:**
- **Host:** an Apple M3 with 8 cores and 8 GB, on macOS 14.3.
- **Docker:** Docker 29.5.2 and Compose 5.5.1, in Colima's VM: aarch64, 4 CPUs, 5 GiB, Ubuntu 24.04.4.

**Time,** for one run of each gate with warm images, timed from the host:

| Gate | Time | Result |
|---|---|---|
| `contract-checks` | 1.0 s | Clean |
| `python-fastapi-checks` | 2.0 s | 5 tests, 100% coverage |
| `go-checks` | 12.3 s | 0 issues; 100% coverage |
| `bench-checks` | 3.0 s | 18 tests, 100% coverage |

`go-checks` is the slowest because each run starts with an empty build cache and compiles with the race detector.

**Disk,** from `docker system df` in the VM, before and after this step:
- **Images:** from 22.81 GB to 26.5 GB.
- **Build cache:** from 17.84 GB to 18.87 GB.

That's about 4.7 GB in all, against 770 MB of compressed downloads. Unpacked, the `golang` and `golangci-lint` images take about 1.3 GB each. golangci-lint's image is used only to copy its binary out of it.

**Each gate fails when it should.** Checked with a mistake planted on purpose, then removed:
- **The contract:** the same file declared as 3.1.0, or with `itemSchema` misspelt, fails Redocly's `struct` rule.
- **Python:** an unused import fails `ruff check` (F401).
- **Go:** a badly formatted file fails `golangci-lint` (gofmt). An untested function brings coverage to 70.6%, below the 90% minimum, and the run fails.
- **Go, by accident:** gosec's G101 took the word "token" in a test's case name for a credential. The case was renamed; the rule stays on.

**Compose's named build context** puts `contract/` in each image without a mount: `ls /contract` in the Python checks image lists its four files ([0011](../spec/decisions/0011-lay-the-repository-out-by-role.md)).

## Measured on 2026-11-09

On the same machine, after plan step 1.4 added the two Go backends and Gin's dependencies.

**`go-checks`,** timed from the host, the checks image built:

| Run | Time | Result |
|---|---|---|
| Cold: both cache volumes just removed | 81.4 s | 0 issues; 92.4% coverage |
| Warm, then again | 11.2 s, then 5.1 s | The same |

- **Why the caches:** before them, every run started with an empty build cache in `/tmp`, and compiled Gin and its dependencies with the race detector: 85 and 90 s for two warm runs.
- **The modules are in the image.** The checks image had fetched them into a BuildKit cache mount, which never reaches the image, so each run downloaded them again. Now `go vet ./...` runs in it with networking off.
- **Disk:** the build cache volume holds 492.8 MB, and golangci-lint's 0.7 MB. The checks image is 387 MB compressed.

## The fake server's gates, on 2026-11-10

On the same Mac, with the checks image built and the caches warm: `fake-server-checks` took 3.8 and 3.5 s, timed from the host, with 0 issues and 97.7% coverage. Its checks image shows as 1.36 GB in `docker image ls`, and the server's own as 22.3 MB.

## In CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs each gate, and the [conformance suite](conformance.md), on every push and pull request, in GitHub Actions ([0019](../spec/decisions/0019-ci-on-github-actions-five-jobs-on-x86-64-with-the-runners-own-docker.md)). Each of its jobs, five at first, and six since the fake server's gates joined on 2026-11-10, runs one of the commands above, on its own runner, with no cache and no secret.

**The runner,** from each job's log on 2026-11-10:
- `ubuntu-24.04`, image 20261101.360.1, x86-64, 4 CPUs and 16 GB;
- Docker 28.0.4 and Compose 2.38.2: older than the Mac's 29.5.2 and 5.5.1. The conformance suite's own Compose, 5.1.4, drove it through the socket.

**Three attempts of the first run,** [42745505829](https://github.com/fkuhne/api-langs-bench/actions/runs/42745505829), on commit `4e67dfd`, each job timed by GitHub:

| Job | Result | Time, three attempts |
|---|---|---|
| The contract's lint | Clean | 11, 9 and 9 s |
| The Python backend's gates | 72 tests, 100% coverage | 21, 19 and 22 s |
| The Go backends' gates | 0 issues; 92.4% coverage | 1 min 53 s, 2 min 4 s, 2 min 3 s |
| The evaluation tool's gates | 147 tests, 100% coverage | 25, 20 and 19 s |
| The conformance suite | 288 passed | 2 min 2 s, 2 min 11 s, 2 min 15 s |

- **Everything passed on x86-64 the first time,** though nothing had been built there before.
- **The run takes as long as its slowest job,** about 2 min 15 s, with no cache. A cache isn't needed yet.
- **The conformance job** spends about 1 minute building the three backends' images and its own, then about 55 s on its checks.

**With the fake server, on 2026-11-10,** in [run 42857893952](https://github.com/fkuhne/api-langs-bench/actions/runs/42857893952) on commit `7bf50e3`, one attempt:

| Job | Result | Time |
|---|---|---|
| The contract's lint | Clean | 14 s |
| The Python backend's gates | 76 tests, 100% coverage | 21 s |
| The Go backends' gates | 92.4% coverage | 2 min 4 s |
| The fake server's gates | 97.7% coverage | 1 min 14 s |
| The evaluation tool's gates | 155 tests, 100% coverage | 19 s |
| The conformance suite | 321 passed | 2 min 35 s |
