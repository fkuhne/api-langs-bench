"""The errors the API answers with their status and their message (contract/README.md#errors),
cut from ai-bootstrap's `app/core/errors.py`."""

import logging
from typing import ClassVar

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.sse import ServerSentEvent
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AppError(Exception):
    """An error the API answers with `status_code`, and its message as the detail."""

    status_code: ClassVar[int] = 500


class ServiceError(AppError):
    """The upstream failed, or refused the request: the message gives its reason."""

    status_code = 502


class ServiceRateLimitedError(ServiceError):
    """The upstream is limiting how often it's called."""

    status_code = 429


class ServiceUnavailableError(ServiceError):
    """The upstream can't be reached, or is down."""

    status_code = 503


class ServiceTimeoutError(ServiceError):
    """The upstream didn't answer in time."""

    status_code = 504


# Each upstream failure by the status it answers, for the fake's `fake_error`.
SERVICE_ERRORS: dict[int, type[ServiceError]] = {
    error.status_code: error
    for error in (
        ServiceError,
        ServiceRateLimitedError,
        ServiceUnavailableError,
        ServiceTimeoutError,
    )
}


class ErrorEvent(BaseModel):
    """Data of an `error` event: the upstream failed after the stream had started."""

    status: int
    detail: str


async def app_error_handler(_request: Request, error: Exception) -> JSONResponse:
    """The error's status, with its message as the detail."""
    status = error.status_code if isinstance(error, AppError) else 500
    if status >= 500:
        logger.warning("%s", error)
    return JSONResponse(status_code=status, content={"detail": str(error)})


def error_event(error: AppError) -> ServerSentEvent:
    """The `error` event that ends a stream the error stopped, with the status the same request
    answers unstreamed."""
    logger.warning("A streamed answer ended with an error: %s", error)
    return ServerSentEvent(
        event="error", data=ErrorEvent(status=error.status_code, detail=str(error))
    )
