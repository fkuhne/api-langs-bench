# The Go backends' images, in stages (spec/decisions/0016):
#   base     the Go toolchain
#   build    one server's binary: SERVER names its folder in cmd/, such as nethttp
#   runtime  that binary alone, run as a non-root user: what `docker compose up` starts
#   dev      golangci-lint too, for `docker compose run --rm go-checks`

FROM golang:1.27.3-trixie AS base
WORKDIR /src

FROM base AS build
COPY go.mod go.sum* ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
ARG SERVER
# As Docker's guide to Go images builds (docs.docker.com/guides/golang/build-images/).
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    test -n "$SERVER" && CGO_ENABLED=0 GOOS=linux go build -o /out/server "./cmd/$SERVER"

# Distroless's static image: no shell and no C library, which a CGO_ENABLED=0 binary doesn't
# need. Pinned by digest, since its tags move.
FROM gcr.io/distroless/static-debian13:nonroot@sha256:25ac8f0c3b2334a9eb05452266bd4697864a8c8ef0ef71e5e6480d7f92868329 AS runtime
# Gin's production mode (spec/decisions/0016); the net/http server ignores it.
ENV GIN_MODE=release
# The fake's tokens, from Compose's named build context (spec/decisions/0011).
COPY --from=contract fake-tokens.json /contract/fake-tokens.json
COPY --from=build /out/server /app/server
USER nonroot:nonroot
EXPOSE 8000
# One process, with Go's defaults, until plan step 3.1's rule (spec/decisions/0016).
ENTRYPOINT ["/app/server"]

FROM base AS dev
# Only the binary, as ai-bootstrap copies uv's.
COPY --from=golangci/golangci-lint:v2.15.0 /usr/bin/golangci-lint /usr/bin/
COPY go.mod go.sum* ./
# Into the image, not a build cache, so the checks find the modules without the network.
RUN go mod download
# The contract, from Compose's named build context (spec/decisions/0011). The checks also mount
# it read-only at the same place, so they see the current file.
COPY --from=contract . /contract/
COPY . .
