# The evaluation tool's image, in stages:
#   base         Python and uv
#   dev          the locked dev tools, for `docker compose run --rm bench-checks`
#   driver       Docker's and Compose's binaries too, to start the backends
#   conformance  the suite, for `docker compose run --rm conformance`
#   runner       oha too, for `docker compose run --rm runner`

FROM python:3.14.8-slim-trixie AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /bin/
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app

FROM base AS dev
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
ENV PATH=/opt/venv/bin:$PATH
# The contract, from Compose's named build context (spec/decisions/0011). The checks also mount
# it read-only at the same place, so they see the current file.
COPY --from=contract . /contract/
COPY . .

# The conformance suite and the runner drive Compose themselves, over Docker's socket, to start
# each backend with the settings they need (spec/decisions/0017). Only the two binaries, as for
# uv's.
FROM dev AS driver
COPY --from=docker:29.5.2-cli /usr/local/bin/docker /usr/local/bin/
COPY --from=docker:29.5.2-cli /usr/local/libexec/docker/cli-plugins/docker-compose \
    /usr/local/libexec/docker/cli-plugins/

FROM driver AS conformance
ENTRYPOINT ["pytest", "conformance"]

# The load generator's binary (spec/decisions/0018).
FROM driver AS runner
COPY --from=ghcr.io/hatoo/oha:1.16.0 /bin/oha /usr/local/bin/
ENTRYPOINT ["python", "-m", "bench.runner"]
