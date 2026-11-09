# 0016. Two Go backends, net/http and Gin, in one module

- Status: Accepted
- Date: 2026-11-09

## Context

Plan step 1.4 builds the Go backend. Version 1 had one framework per language, with "Go's standard library against a framework" left for later ([product](../product.md#scope)). On 2026-11-09 the owner asked to measure both: the standard library, and a framework.

What was read on 2026-11-09:
- **Use:** in JetBrains' 2025 survey of Go developers, Gin is used by 48%, Echo by 16% and Fiber by 11%, and `net/http` is the most common router. That's from search summaries; JetBrains' page refused our fetch.
- **GitHub:** Gin has 89.6k stars (v1.12.0, released 2026-02-28), Fiber 40.3k (v3.7.0), Echo 32.8k (v5.4.4), chi 23.1k (v5.5.0).
- **The servers underneath:** Gin, Echo and chi run on `net/http`. Fiber runs on fasthttp, its own HTTP server. The only sign we found that a fasthttp stream's client has left is a failed write, and Fiber has open issues about SSE ([fiber#2837](https://github.com/gofiber/fiber/issues/2837)).
- **Routing:** since Go 1.22, the standard library's `ServeMux` routes by method and by path pattern ([Go 1.22's release notes](https://go.dev/doc/go1.22#enhanced_routing_patterns)). chi's main gain over it is gone.
- **Gin's SSE:** `c.SSEvent` writes `event:` and `data:` lines, with no space after the colon, and the data as JSON from `encoding/json`. It sets `Content-Type: text/event-stream` and `Cache-Control: no-cache` (gin-contrib/sse v1.1.0, `sse-encoder.go`). `c.Stream` stops when the client leaves, through `net/http`'s `CloseNotify` (Gin v1.12.0, `context.go`, lines 1313-1337).
- **Docker's guide to Go images** builds with `CGO_ENABLED=0 GOOS=linux go build`, and runs the binary on a distroless image as `nonroot` ([Docker's guide](https://docs.docker.com/guides/golang/build-images/)).

## Decision

Go gets two backends in version 1: one on the standard library's `net/http`, one on Gin v1.12.0. They share one module, in `backends/go/`. The settings, the errors, the LLM port and the fake are written once. Each server is its own HTTP layer, with its own binary, image and Compose service.

- **The layout:**
  - `internal/settings`, `internal/llm` and `internal/fake`: the shared parts;
  - `internal/app`: start-up, and the same `http.Server` for both;
  - `internal/nethttp` and `internal/ginserver`: the two HTTP layers;
  - `cmd/nethttp` and `cmd/gin`: the two binaries.
- **The services:** `go-nethttp`, published on `127.0.0.1:${GO_NETHTTP_PORT:-8002}`, and `go-gin`, on `127.0.0.1:${GO_GIN_PORT:-8003}`.
- **Each HTTP layer is written as its documentation shows:**
  - **`net/http`:** `ServeMux` with method patterns, `encoding/json`, and the events written by hand, each flushed through `http.ResponseController`;
  - **Gin:** `gin.Default()`, with its logger and its recovery; `ShouldBindJSON` with `binding` tags; `c.JSON`; `c.SSEvent`, flushed after each event; and `GIN_MODE=release`.
- **Shared by both:**
  - **The request's parameters** are one type, decoded the same way. Numbers keep their text, so `5` is a whole number and `5.0` isn't, as in Python. Reserved keys are refused.
  - **The server:** one `http.Server` set-up. It has a 10 s `ReadHeaderTimeout` (gosec's rule) and no write timeout, which would cut long streams. It stops gracefully on SIGTERM.
  - **A leaving client** cancels the request's context, which stops the fake.
- **No keep-alive comment.** The contract allows `: ping` but doesn't ask for it, and neither `net/http` nor Gin sends one. FastAPI's does.
- **The image:** built as Docker's guide shows, on distroless's static Debian 13 image (the binary needs no C library), pinned by digest, run as `nonroot`. The image has no shell, so the binary has a `healthcheck` command for Compose.
- **The run:** one process, with Go's defaults, until plan step 3.1's rule.
- **The scope:** version 1 has three backends, FastAPI, `net/http` and Gin, in two languages, as [0002](0002-start-with-python-and-go-then-add-languages-one-at-a-time.md) planned. [0011](0011-lay-the-repository-out-by-role.md)'s rule that renames Go's folder after its framework is superseded: the folder stays `backends/go/`.
- **The step** stays 1.4, built in two halves: `net/http` with the shared parts first, measured; then Gin.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| `net/http` alone, as version 1 had it | The owner wants to see what a framework costs, and Gin is what most Go developers use |
| Echo beside `net/http` | A third as many users as Gin, on the same server underneath |
| Fiber beside `net/http` | The widest contrast, being a different server. But a fasthttp stream may not learn that its client left, which the contract requires and plan step 3.3 measures |
| chi beside `net/http` | Plain `http.Handler`s; since Go 1.22 it adds little that the standard router lacks |
| Two complete folders, `backends/go-nethttp/` and `backends/go-gin/` | The fake would be written twice, and a difference between the copies could reach the numbers |
| Gin's `c.Stream` helper | It polls `CloseNotify`, which `net/http` deprecates in favour of the request's context. The context already stops the fake |

## Consequences

- The two Go backends differ only in their HTTP layer, which is what's being compared.
- `docker compose run --rm go-checks` checks both.
- Python keeps one framework. A framework-free Python, or Litestar, stays in Next.
- The conformance suite (plan step 1.5) runs against three backends.
- **Learned while building it, 2026-11-09:**
  - Go's coverage gate counts every package's lines run by any package's tests (`-coverpkg=./...`), as pytest-cov does, since the contract's checks in `internal/apitest` run from each server's tests.
  - Go's own HTTP client closes a body closed early up to 50 ms late, to reuse its connection. A client that measures leaving must turn keep-alive off ([notes](../../docs/benchmarking.md#measuring-latency-without-fooling-ourselves)).
  - Gin's binary links every codec it can bind or render, and HTTP/3's quic-go: 28.7 MiB against `net/http`'s 9.6 MiB.
  - `go-mod` rewrites `go.mod` and `go.sum` in Docker, and the Go gates keep their caches in named volumes ([gates](../../docs/gates.md#measured-on-2026-11-09)).

## Assumptions to verify

- [x] In both servers, a client that leaves cancels the request's context, and the fake stops within one token's gap. Checked by a test in this step; measured under load in plan step 3.3. *net/http, 2026-11-09: at most one more token, in 20 runs out of 20; the context is cancelled 0.2 ms after the client closes its connection. Go's own HTTP client closes it up to 50 ms late, so the test turns its keep-alive off ([backends](../../docs/backends.md#go-nethttp)).* *Gin, 2026-11-09: the same, at most one more token in 20 runs out of 20 ([backends](../../docs/backends.md#go-gin)).*
- [x] `GIN_MODE=release`, the logger and the recovery are what Gin's documentation shows for production. To check in this step. *2026-11-09: Gin's [deployment page](https://gin-gonic.com/en/docs/deployment/) lists `GIN_MODE` without recommending a mode, and shows `gin.Default()`. Gin's own warning in debug mode says to `Switch to "release" mode in production`, `using env: export GIN_MODE=release` (v1.12.0, `debug.go`). `gin.Default()` is `New()` with `Logger()` and `Recovery()` (`gin.go`). Gin also warns that trusting all proxies "is NOT safe", so the router trusts none.*
- [x] `encoding/json` writes `<` as `\u003c`, as the contract's page says from memory. To check in this step. *2026-11-09: it does, and `&` as `\u0026` ([backends](../../docs/backends.md#go-nethttp)).*

## Sources

- Search summaries of [JetBrains' Go ecosystem report, 2025](https://blog.jetbrains.com/go/2025/11/10/go-language-trends-ecosystem-2025/), and [a comparison of Go web frameworks](https://glukhov.org/app-architecture/api-architecture/go-web-frameworks-stdlib-chi-gin-echo-fiber/), read on 2026-11-09.
- GitHub's API for each repository's stars and latest release, 2026-11-09.
- Gin v1.12.0's `context.go`, `gin.go`, `debug.go` and `go.mod`, and gin-contrib/sse v1.1.0's `sse-encoder.go`, read on 2026-11-09.
- Gin's [deployment page](https://gin-gonic.com/en/docs/deployment/), read on 2026-11-09.
- Our runs on 2026-11-09 ([backends](../../docs/backends.md#go-nethttp)).
- [Docker's guide to building Go images](https://docs.docker.com/guides/golang/build-images/), read on 2026-11-09.
- The owner's picks, 2026-11-09.
