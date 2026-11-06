"""The LLM client the routes use: the one the lifespan made."""

from typing import Annotated, cast

from fastapi import Depends, Request

from app.llm.port import LLMClient


def get_llm_client(request: Request) -> LLMClient:
    return cast(LLMClient, request.app.state.llm_client)


LLMClientDep = Annotated[LLMClient, Depends(get_llm_client)]
