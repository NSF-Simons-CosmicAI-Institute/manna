"""Structured stdlib logging plus a request-scoped ContextVar.

The ContextVar (``current_request_id``) is set by Starlette middleware in
``app.py`` on each inbound HTTP request. Tool code reads it via
``current_request_id.get()`` to thread an opaque ID through error payloads
and log records. In-memory MCP client tests bypass the HTTP stack, so the
ContextVar will return ``None`` there — that is expected and the tools tolerate
it.
"""

import contextvars
import json
import logging
import sys
import uuid

current_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_request_id", default=None
)


def new_request_id() -> str:
    """Generate a fresh opaque request ID for the inbound request."""
    return uuid.uuid4().hex[:12]


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }
        rid = current_request_id.get()
        if rid is not None:
            payload["request_id"] = rid
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers[:] = [handler]
