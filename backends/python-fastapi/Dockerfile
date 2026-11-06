# The Python backend's image, in stages:
#   base     Python and uv
#   deps     the locked dependencies, without the dev tools
#   runtime  the app, run as a non-root user: what `docker compose up` starts
#   dev      the dev tools too, for `docker compose run --rm python-fastapi-checks`

FROM python:3.14.8-slim-trixie AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /bin/
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app

FROM base AS deps
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM python:3.14.8-slim-trixie AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
# The fake's tokens, from Compose's named build context (spec/decisions/0011).
COPY --from=contract fake-tokens.json /contract/fake-tokens.json
COPY app ./app
USER app
EXPOSE 8000
# One process, with uvicorn's defaults, until plan step 3.1's rule (spec/decisions/0014).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS dev
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
ENV PATH=/opt/venv/bin:$PATH
# The contract, from Compose's named build context (spec/decisions/0011). The checks also mount
# it read-only at the same place, so they see the current file.
COPY --from=contract . /contract/
COPY . .
