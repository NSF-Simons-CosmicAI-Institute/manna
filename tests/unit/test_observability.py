"""Direct coverage of observability.py: JSON formatter, request IDs, configuration."""

import json
import logging
import sys

from manna.observability import (
    _JsonFormatter,
    configure_logging,
    current_request_id,
    new_request_id,
)


def _record(msg: str = "hello", exc_info=None) -> logging.LogRecord:
    return logging.LogRecord(
        name="manna.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )


def test_new_request_id_is_12_hex_chars_and_unique():
    rid = new_request_id()
    assert len(rid) == 12
    int(rid, 16)  # raises ValueError if not hex
    assert new_request_id() != rid


def test_formatter_emits_json_with_core_fields():
    payload = json.loads(_JsonFormatter().format(_record("boom")))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "manna.test"
    assert payload["message"] == "boom"
    assert "time" in payload


def test_formatter_omits_request_id_when_unset():
    token = current_request_id.set(None)
    try:
        payload = json.loads(_JsonFormatter().format(_record()))
        assert "request_id" not in payload
    finally:
        current_request_id.reset(token)


def test_formatter_includes_request_id_when_set():
    token = current_request_id.set("abc123def456")
    try:
        payload = json.loads(_JsonFormatter().format(_record()))
        assert payload["request_id"] == "abc123def456"
    finally:
        current_request_id.reset(token)


def test_formatter_includes_exc_info():
    try:
        raise ValueError("kaboom")
    except ValueError:
        rec = _record("failed", exc_info=sys.exc_info())
    payload = json.loads(_JsonFormatter().format(rec))
    assert "ValueError: kaboom" in payload["exc_info"]


def test_configure_logging_installs_single_stderr_json_handler():
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging(level="WARNING")
        assert len(root.handlers) == 1
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is sys.stderr
        assert isinstance(handler.formatter, _JsonFormatter)
        assert root.level == logging.WARNING
        configure_logging(level="INFO")  # idempotent: still exactly one handler
        assert len(logging.getLogger().handlers) == 1
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
