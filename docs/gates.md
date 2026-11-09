# The gates

Each part of the repository has gates: checks that fail on a mistake, run in Docker the same way on every machine, and in CI from plan step 1.7. They're about equally strict for every language ([0013](../spec/decisions/0013-gates-equally-strict-for-every-language.md)). They check the code, not its speed.

## What runs

| Command | Checks | Versions |
|---|---|---|
| `docker compose run --rm contract-checks` | [`contract/openapi.yaml`](../contract/openapi.yaml), with Redocly's recommended rules except one ([`redocly.yaml`](../contract/redocly.yaml)) | Redocly CLI 2.69.0 |
| `docker compose run --rm python-fastapi-checks` | [`backends/python-fastapi/`](../backends/python-fastapi/): `ruff check` with 16 rule families, `ruff format --check`, `mypy --strict`, and pytest with branch coverage of at least 90% and warnings as errors | Python 3.14.8, uv 0.12.24, ruff 0.16.10, mypy 2.4.0, pytest 9.1.1, pytest-cov 7.1.0, as ai-bootstrap |
| `docker compose run --rm go-checks` | [`backends/go/`](../backends/go/): `golangci-lint run` ([`.golangci.yml`](../backends/go/.golangci.yml): the standard linters, plus gosec, bodyclose, noctx, errorlint and revive, with gofmt and goimports), then `go test -race -shuffle=on`, failing below 90% coverage. Coverage counts every package's lines run by any package's tests (`-coverpkg=./...`), as pytest-cov counts the Python backend's; the shared contract tests in `internal/apitest` run from each server's tests | Go 1.27.3, golangci-lint 2.15.0 |
| `docker compose run --rm bench-checks` | [`bench/`](../bench/): the Python backend's gates | As the Python backend, plus jsonschema 4.26.0, PyYAML 6.0.3 and referencing 0.37.0 |

Each checks service mounts its folder and `contract/` read-only, so it checks the current files. After a dependency changes:
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
