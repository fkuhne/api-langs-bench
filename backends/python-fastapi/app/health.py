"""Liveness for the process, readiness for its upstream (contract/README.md#the-endpoints)."""

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.llm.dependencies import LLMClientDep

router = APIRouter(prefix="/health", tags=["health"])

CheckStatus = Literal["ok", "unavailable"]


class Liveness(BaseModel):
    """The process is up and serving requests."""

    status: Literal["ok"] = "ok"


class Readiness(BaseModel):
    """Whether the upstream can serve requests."""

    status: CheckStatus
    checks: dict[str, CheckStatus]


@router.get("", summary="Liveness")
async def liveness() -> Liveness:
    return Liveness()


@router.get("/ready", summary="Readiness")
async def readiness(llm: LLMClientDep, response: Response) -> Readiness:
    check: CheckStatus = "ok" if await llm.is_ready() else "unavailable"
    if check != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Readiness(status=check, checks={"llm": check})
