"""Contract tests for the error envelope.

The LLM relies on a fixed shape: `error_class`, `message`, `retry_strategy`,
`request_id`. These tests enforce:

- Every `ToolExecutionError` subclass produces a conforming payload.
- `retry_strategy` is always a value the `RetryStrategy` Literal allows.
- `error_class` strings are non-empty and snake_case (LLM-facing
  discriminator).
- `wrap_tool_errors` coerces unknown exceptions to `InternalError` and
  redacts the message.
- Required keys are always present; optional keys (`hint`,
  `retry_after_seconds`) appear only when set.

When a new error subclass is added, just appending it to
`ALL_ERROR_SUBCLASSES` brings it under coverage.
"""

import re
from typing import get_args

import pytest

from manna import errors as errors_module
from manna.errors import (
    ArchiveError,
    DalQueryError,
    InternalError,
    JobGoneError,
    JobNotReadyError,
    RetryStrategy,
    TimeoutArchiveError,
    ToolExecutionError,
    ValidationError,
    error_to_payload,
    wrap_tool_errors,
)

# Listed explicitly (not auto-discovered) so the test fails loudly
# when a new subclass lands and we forget to include it. Forgetting
# = no contract coverage for the new shape.
ALL_ERROR_SUBCLASSES = (
    ValidationError,
    ArchiveError,
    DalQueryError,
    JobNotReadyError,
    JobGoneError,
    InternalError,
    TimeoutArchiveError,
)

VALID_RETRY_STRATEGIES = set(get_args(RetryStrategy))

REQUIRED_PAYLOAD_KEYS = {"error_class", "message", "retry_strategy", "request_id"}
OPTIONAL_PAYLOAD_KEYS = {"hint", "retry_after_seconds"}


def test_contract_test_covers_every_subclass_in_errors_module():
    """If you add a new ToolExecutionError subclass to errors.py, you
    must also add it to ALL_ERROR_SUBCLASSES above. This test fails
    when those drift apart."""
    in_module = {
        v
        for v in vars(errors_module).values()
        if isinstance(v, type) and issubclass(v, ToolExecutionError) and v is not ToolExecutionError
    }
    covered = set(ALL_ERROR_SUBCLASSES)
    missing = in_module - covered
    assert not missing, (
        f"New ToolExecutionError subclasses missing from "
        f"ALL_ERROR_SUBCLASSES in this contract test: "
        f"{sorted(c.__name__ for c in missing)}"
    )


@pytest.mark.parametrize("cls", ALL_ERROR_SUBCLASSES, ids=lambda c: c.__name__)
def test_error_class_string_is_snake_case_nonempty(cls):
    err = cls(message="x")
    assert err.error_class, f"{cls.__name__} has empty error_class"
    assert re.fullmatch(r"[a-z][a-z0-9_]*", err.error_class), (
        f"{cls.__name__}.error_class = {err.error_class!r} is not lowercase snake_case"
    )


@pytest.mark.parametrize("cls", ALL_ERROR_SUBCLASSES, ids=lambda c: c.__name__)
def test_retry_strategy_is_in_literal(cls):
    err = cls(message="x")
    assert err.retry_strategy in VALID_RETRY_STRATEGIES, (
        f"{cls.__name__}.retry_strategy = {err.retry_strategy!r} not in "
        f"RetryStrategy literal {sorted(VALID_RETRY_STRATEGIES)}"
    )


@pytest.mark.parametrize("cls", ALL_ERROR_SUBCLASSES, ids=lambda c: c.__name__)
def test_payload_has_all_required_keys(cls):
    err = cls(message="boom")
    payload = error_to_payload(err, request_id="req-abc")
    missing = REQUIRED_PAYLOAD_KEYS - payload.keys()
    assert not missing, (
        f"{cls.__name__} payload missing required keys: {missing}; got {sorted(payload.keys())}"
    )


@pytest.mark.parametrize("cls", ALL_ERROR_SUBCLASSES, ids=lambda c: c.__name__)
def test_payload_has_no_unknown_keys(cls):
    err = cls(message="boom")
    payload = error_to_payload(err, request_id="req-abc")
    extra = set(payload) - REQUIRED_PAYLOAD_KEYS - OPTIONAL_PAYLOAD_KEYS
    assert not extra, (
        f"{cls.__name__} payload has unexpected keys: {extra}. "
        f"Add them to OPTIONAL_PAYLOAD_KEYS in this contract test "
        f"if intentional."
    )


@pytest.mark.parametrize("cls", ALL_ERROR_SUBCLASSES, ids=lambda c: c.__name__)
def test_optional_keys_omitted_when_unset(cls):
    """`hint` and `retry_after_seconds` should NOT appear unless set —
    they cost tokens in the LLM-facing payload."""
    err = cls(message="boom")  # no hint, no retry_after_seconds
    payload = error_to_payload(err, request_id="req-abc")
    assert "hint" not in payload, f"{cls.__name__}: hint key present when unset"
    assert "retry_after_seconds" not in payload, (
        f"{cls.__name__}: retry_after_seconds key present when unset"
    )


@pytest.mark.parametrize("cls", ALL_ERROR_SUBCLASSES, ids=lambda c: c.__name__)
def test_hint_propagates_when_set(cls):
    err = cls(message="boom", hint="try again with X")
    payload = error_to_payload(err, request_id="req-abc")
    assert payload.get("hint") == "try again with X"


def test_internal_error_message_is_redacted():
    """InternalError must NEVER leak the original message — it might
    contain secrets or stack traces."""
    err = InternalError(message="POSTGRES PWD=hunter2 leaked")
    payload = error_to_payload(err, request_id="req-abc")
    assert "hunter2" not in payload["message"]
    assert "Internal server error" in payload["message"]


def test_unknown_exception_coerced_to_internal_error_redacted():
    """Plain Exception coming through wrap_tool_errors must end up
    redacted, not leaked as a raw message."""

    @wrap_tool_errors
    def explodes():
        raise ValueError("SECRET sql=DROP TABLE users")

    payload = explodes()
    assert payload["error_class"] == "internal_error"
    assert "SECRET" not in payload["message"]
    assert "Internal server error" in payload["message"]
    assert payload["retry_strategy"] in VALID_RETRY_STRATEGIES


def test_request_id_argument_used_when_error_has_none():
    """When the error didn't capture request_id at raise time, the
    caller's id wins."""
    err = ValidationError(message="bad")
    payload = error_to_payload(err, request_id="incoming-req-77")
    assert payload["request_id"] == "incoming-req-77"


def test_error_request_id_wins_over_argument():
    """When both are set, the error's captured request_id wins —
    documented behaviour in error_to_payload."""
    err = ValidationError(message="bad", request_id="captured-at-raise")
    payload = error_to_payload(err, request_id="caller-later")
    assert payload["request_id"] == "captured-at-raise"


def test_wrap_tool_errors_rejects_async_callables():
    """The decorator is sync-only; documented in the docstring."""

    async def asyncy():
        pass

    with pytest.raises(TypeError, match="sync-only"):
        wrap_tool_errors(asyncy)


def test_tool_execution_error_subclasses_each_have_unique_error_class():
    """The error_class string IS the LLM's discriminator. Two subclasses
    sharing one string would make the LLM unable to tell them apart."""
    seen: dict[str, type] = {}
    for cls in ALL_ERROR_SUBCLASSES:
        instance = cls(message="x")
        if cls is InternalError:
            # InternalError shares "internal_error" with the base — that's
            # the redaction sentinel. Other subclasses must be unique.
            assert instance.error_class == "internal_error"
            continue
        if cls is TimeoutArchiveError:
            # Deliberately shares "archive_error" with its parent: the wire
            # contract is unchanged, only the Python type differs (so the
            # auto-promote path can branch on a timeout without string
            # matching). The LLM still sees a plain archive_error.
            assert instance.error_class == "archive_error"
            continue
        ec = instance.error_class
        assert ec not in seen, (
            f"{cls.__name__} and {seen[ec].__name__} both use "
            f"error_class={ec!r}; the LLM can't disambiguate"
        )
        seen[ec] = cls
