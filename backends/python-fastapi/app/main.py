"""The app: the contract's four endpoints, under /api. Run with `uvicorn app.main:app`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import chat, health
from app.errors import AppError, app_error_handler
from app.llm.factory import create_llm_client
from app.settings import Settings

API_PREFIX = "/api"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Read the settings and make the LLM client at start-up; close it at shutdown. An invalid
    setting stops the start-up here."""
    llm_client = create_llm_client(Settings())
    app.state.llm_client = llm_client
    try:
        yield
    finally:
        await llm_client.aclose()


def create_app() -> FastAPI:
    """The routes and the errors. The served docs are off: the contract has none."""
    app = FastAPI(
        title="api-langs-bench: Python, FastAPI",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(chat.router, prefix=API_PREFIX)
    app.add_exception_handler(AppError, app_error_handler)
    return app


app = create_app()
