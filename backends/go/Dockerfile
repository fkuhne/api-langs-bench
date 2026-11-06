# The Go backend's image, in stages:
#   base  the Go toolchain
#   dev   golangci-lint too, for `docker compose run --rm go-checks`
# The runtime stage arrives with the backend itself (plan step 1.4).

FROM golang:1.27.3-trixie AS base
WORKDIR /src

FROM base AS dev
# Only the binary, as ai-bootstrap copies uv's.
COPY --from=golangci/golangci-lint:v2.15.0 /usr/bin/golangci-lint /usr/bin/
COPY go.mod go.sum* ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
# The contract, from Compose's named build context (spec/decisions/0011). The checks also mount
# it read-only at the same place, so they see the current file.
COPY --from=contract . /contract/
COPY . .
