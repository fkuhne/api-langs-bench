# The fake upstream server's images, in stages (spec/decisions/0023):
#   base     the Go toolchain
#   build    the server's binary
#   runtime  that binary alone, run as a non-root user: what `docker compose up` starts
#   dev      golangci-lint too, for `docker compose run --rm fake-server-checks`

FROM golang:1.27.3-trixie AS base
WORKDIR /src

FROM base AS build
COPY go.mod go.sum* ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
# As Docker's guide to Go images builds (docs.docker.com/guides/golang/build-images/).
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux go build -o /out/server ./cmd/fake-server

# Distroless's static image, as the Go backends' (spec/decisions/0016). Pinned by digest, since
# its tags move.
FROM gcr.io/distroless/static-debian13:nonroot@sha256:25ac8f0c3b2334a9eb05452266bd4697864a8c8ef0ef71e5e6480d7f92868329 AS runtime
# The fake's tokens, from Compose's named build context (spec/decisions/0011).
COPY --from=contract fake-tokens.json /contract/fake-tokens.json
COPY --from=build /out/server /app/server
USER nonroot:nonroot
EXPOSE 8080
ENTRYPOINT ["/app/server"]

FROM base AS dev
# Only the binary, as ai-bootstrap copies uv's.
COPY --from=golangci/golangci-lint:v2.15.0 /usr/bin/golangci-lint /usr/bin/
COPY go.mod go.sum* ./
RUN go mod download
# The contract, from Compose's named build context (spec/decisions/0011). The checks also mount
# it read-only at the same place, so they see the current file.
COPY --from=contract . /contract/
COPY . .
