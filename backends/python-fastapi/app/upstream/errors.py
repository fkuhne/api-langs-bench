"""An upstream's failures as the contract's errors (contract/README.md#the-upstream). The
mapping is ai-bootstrap's, in its `app/core/services.py` and `app/llm/openai_errors.py`."""

import httpx2

from app.errors import (
    ServiceError,
    ServiceRateLimitedError,
    ServiceTimeoutError,
    ServiceUnavailableError,
)

# How the upstream is named in an error's detail.
SERVICE = "The LLM endpoint"

RATE_LIMITED = 429
# The statuses that mean the upstream is down, not that it refused this request.
DOWN = frozenset({502, 503, 504, 529})

# How much of the upstream's own reason an error's detail carries.
REASON_CHARACTERS = 200


def status_error(status: int, body: object) -> ServiceError:
    """The error a failed answer is: rate-limited for a 429; unavailable while the upstream is
    down; any other status a refusal, with its reason."""
    if status == RATE_LIMITED:
        return ServiceRateLimitedError(f"{SERVICE} is rate-limiting requests.")
    if status in DOWN:
        return ServiceUnavailableError(f"{SERVICE} failed with status {status}{reason(body)}")
    return ServiceError(f"{SERVICE} refused the request with status {status}{reason(body)}")


def stream_error(error: object) -> ServiceError:
    """The error an `error` object inside a stream is, by its code. Without a whole number as
    its code, it's a refusal."""
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, int) and not isinstance(code, bool):
        return status_error(code, {"error": error})
    return ServiceError(f"{SERVICE} failed inside its stream{reason({'error': error})}")


def transport_error(error: httpx2.HTTPError) -> ServiceError:
    """The error a request that got no answer is: timed out, or unreachable."""
    # A timeout is a transport error too, so it's checked first.
    if isinstance(error, httpx2.TimeoutException):
        return ServiceTimeoutError(f"{SERVICE} didn't answer in time.")
    return ServiceUnavailableError(f"{SERVICE} can't be reached.")


def unreadable() -> ServiceError:
    """The upstream answered something that isn't the API's answer."""
    return ServiceError(f"{SERVICE} sent an answer the backend can't read.")


def reason(body: object) -> str:
    """The upstream's own reason in an error's body: `: <reason>`, or `.` when it gives none.
    It reads OpenAI's `{"error": {"message": …}}`, a plain `{"error": …}` and `{"detail": …}`."""
    found: object = None
    if isinstance(body, dict):
        found = body.get("error", body.get("detail"))
        if isinstance(found, dict):
            found = found.get("message")
    if not isinstance(found, str) or not found.strip():
        return "."
    return f": {found.strip()[:REASON_CHARACTERS]}"
