# 0013. Gates equally strict for every language

- Status: Accepted
- Date: 2026-11-06

## Context

Each language gets quality gates, run in Docker and in CI (R18). They don't touch speed. But a backend held to weaker gates may be written more carelessly, which goes against R6: every backend is written as a competent engineer would.

ai-bootstrap's Python gates, read in its [`pyproject.toml`](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/pyproject.toml) and [`compose.yaml`](https://github.com/fkuhne/ai-bootstrap/blob/main/compose.yaml) on 2026-11-06:
- **ruff:** `ruff check`, with 16 rule families including security (`S`) and async (`ASYNC`), and `ruff format --check`;
- **mypy:** `mypy --strict`;
- **import-linter,** for its module layers;
- **pytest,** with branch coverage of at least 90%, and any warning failing its test.

Go's compiler checks types. Its toolchain adds `gofmt` and `go vet`, but no security or HTTP checks. golangci-lint v2 runs many linters and formatters from one binary and one config. Its image is `golangci/golangci-lint:v2.15.0`, which Docker Hub lists from 2026-10-16, at 332 MB compressed.

The contract is OpenAPI 3.2, to be linted here, or else fall back to 3.1 ([0010](0010-the-contract-ai-bootstraps-chat-in-text-paced-fakes-and-openapi-3-2.md)).

## Decision

Every language's gates are about equally strict, and each runs as `docker compose run --rm <name>-checks`:
- **Python,** for each backend and for `bench/`, uses ai-bootstrap's gates without `import-linter`, since one small module has no layers to guard. Base image `python:3.14.8-slim-trixie`, as ai-bootstrap uses.
- **Go:**
  - `golangci-lint` v2, with its standard linters (`errcheck`, `govet`, `ineffassign`, `staticcheck`, `unused`);
  - plus `gosec` (as ruff's `S`), `bodyclose` and `noctx` (HTTP calls), `errorlint` and `revive`;
  - with `gofmt` and `goimports` as formatters;
  - then `go test -race -shuffle=on`, with coverage of at least 90%, checked by a small script, since Go has no built-in minimum;
  - the binary is copied from golangci-lint's image into a `golang` build image, as ai-bootstrap copies `uv`.
- **The contract:** a pinned Redocly CLI lints `contract/openapi.yaml`. If it rejects 3.2, Spectral is tried, then 3.1.
- **No vulnerability scan for now,** in either language, to keep the two equal.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| Go's toolchain only: `gofmt`, `go vet`, `go test -race` | Weaker than Python's gates: no security or HTTP checks |
| The toolchain plus `staticcheck` | Still no security checks, and no check that HTTP response bodies are closed |
| A vulnerability scan for each language | Worth having later, for both languages at once. Neither has one now |

## Consequences

- A new language arrives with gates as strict as these. The `add-language` skill will say how.
- CI runs the same commands (step 1.7).
- Go's checks image pulls golangci-lint's image only to copy its binary out of it: about 1.3 GB unpacked ([gates](../../docs/gates.md#measured-on-2026-11-06)).
- `golangci-lint run` reports unformatted files itself, so Go's gates need no separate format step.

## Assumptions to verify

- [ ] golangci-lint v2's linters, as chosen, are about as strict as ruff's selected families. Judged by reading, not measured; reviewed once both backends exist (step 1.4).
- [x] Redocly CLI lints OpenAPI 3.2, as [0010](0010-the-contract-ai-bootstraps-chat-in-text-paced-fakes-and-openapi-3-2.md) assumes. To check in this step. *Checked on 2026-11-06 with Redocly CLI 2.69.0 (`docker compose run --rm contract-checks`, on Colima on the owner's M3): `contract/openapi.yaml` lints clean as 3.2.0. The same file declared as 3.1.0, or with `itemSchema` misspelt, fails its `struct` rule, so the 3.2 structure is checked, not skipped.*

## Sources

- ai-bootstrap's gates, as above.
- Docker Hub's tags for `golangci/golangci-lint`, `golang`, `python` and `redocly/cli`, read on 2026-11-06.
- The owner's pick, 2026-11-06.
