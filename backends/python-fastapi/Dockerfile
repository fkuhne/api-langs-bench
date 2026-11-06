# The Python backend's image, in stages:
#   base  Python and uv
#   dev   the locked dev tools, for `docker compose run --rm python-fastapi-checks`
# The runtime stage arrives with the backend itself (plan step 1.3).

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
