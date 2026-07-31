import asyncio
import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Literal

from manna.observability import current_request_id

RetryStrategy = Literal[
    "fix_and_retry",
    "wait_and_retry",
    "submit_async",
    "abandon",
    "poll",
]


@dataclass
class ToolExecutionError(Exception):
    """Base class — every concrete subclass sets error_class + retry_strategy.

    Subclasses that should have their message redacted in the LLM-facing
    payload (e.g. internal server errors) override redact_message to True.
    """

    redact_message: ClassVar[bool] = False
    error_class: str = "internal_error"
    retry_strategy: RetryStrategy = "abandon"
    message: str = ""
    hint: str | None = None
    retry_after_seconds: int | None = None
    request_id: str | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)


@dataclass
class ValidationError(ToolExecutionError):
    error_class: str = "validation_error"
    retry_strategy: RetryStrategy = "fix_and_retry"


@dataclass
class ArchiveError(ToolExecutionError):
    error_class: str = "archive_error"
    retry_strategy: RetryStrategy = "wait_and_retry"


@dataclass
class TimeoutArchiveError(ArchiveError):
    """A sync request that exceeded the client timeout.

    Distinct Python type so vo_tap_query's auto-promote path can branch on
    the failure mode directly, instead of substring-matching the error
    message. The wire contract is unchanged: error_class stays
    'archive_error' and a sync-mode caller sees an ordinary archive_error.
    """


@dataclass
class DalQueryError(ToolExecutionError):
    error_class: str = "tap_query_error"
    retry_strategy: RetryStrategy = "fix_and_retry"


# Backward-compat alias. Remove once no callers remain.
TapQueryError = DalQueryError


@dataclass
class JobNotReadyError(ToolExecutionError):
    """Raised by vo_tap_results when the job exists but hasn't finished yet.

    The retry_strategy "poll" tells the LLM to call vo_tap_status in a
    loop instead of retrying vo_tap_results immediately.
    """

    error_class: str = "job_not_ready"
    retry_strategy: RetryStrategy = "poll"


@dataclass
class JobGoneError(ToolExecutionError):
    """The upstream job no longer exists (UWS 404/410).

    Distinct from ArchiveError because the retry advice is the opposite: a job
    that has been deleted or aged out of the archive's UWS store will never
    come back, so 'wait_and_retry' would loop the model forever. Since the
    server keeps no job registry, this upstream status is the *only* signal
    that a job_url is dead.
    """

    error_class: str = "job_gone"
    retry_strategy: RetryStrategy = "abandon"


@dataclass
class InternalError(ToolExecutionError):
    redact_message: ClassVar[bool] = True
    error_class: str = "internal_error"
    retry_strategy: RetryStrategy = "abandon"


_INTERNAL_GENERIC_MESSAGE = "Internal server error. Contact ops with request_id."


def error_to_payload(err: Exception, *, request_id: str | None = None) -> dict:
    """Convert any error into the LLM-facing payload shape.

    Unknown exceptions (anything not a ToolExecutionError) are coerced into
    InternalError; the original exception is attached as __cause__ so the
    caller's logger can still recover it.

    The LLM-facing payload omits hint and retry_after_seconds when not present
    to save tokens; callers should use payload.get(...) on those keys.
    """
    if not isinstance(err, ToolExecutionError):
        original = err
        err = InternalError(message="", request_id=request_id)
        err.__cause__ = original

    payload: dict = {
        "error_class": err.error_class,
        "message": (_INTERNAL_GENERIC_MESSAGE if err.redact_message else err.message),
        "retry_strategy": err.retry_strategy,
        "request_id": err.request_id or request_id,
    }
    if err.hint:
        payload["hint"] = err.hint
    if err.retry_after_seconds is not None:
        payload["retry_after_seconds"] = err.retry_after_seconds
    return payload


def wrap_tool_errors(fn: Callable) -> Callable:
    """Decorate an MCP tool so all errors flow through the structured payload path.

    Catches ToolExecutionError subclasses (preserving error_class/retry_strategy)
    and bare Exception (coerced to InternalError with redacted message).
    Threads the current request_id from the ContextVar into the payload.
    Logs at WARN level for expected errors, EXCEPTION for unexpected.
    """
    name = fn.__name__
    if asyncio.iscoroutinefunction(fn):
        raise TypeError(
            f"wrap_tool_errors is sync-only; {name} is async. "
            "Slice 3 will introduce an async variant if needed."
        )
    log = logging.getLogger(f"manna.tools.{name}")

    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolExecutionError as e:
            log.warning("%s: %s", name, e.error_class)
            return error_to_payload(e, request_id=current_request_id.get())
        except Exception as e:  # noqa: BLE001
            log.exception("%s: unexpected error", name)
            return error_to_payload(e, request_id=current_request_id.get())

    return wrapped
