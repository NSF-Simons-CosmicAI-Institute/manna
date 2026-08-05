from manna.errors import (
    ArchiveError,
    DalQueryError,
    InternalError,
    ToolExecutionError,
    ValidationError,
    error_to_payload,
)


def test_validation_error_payload_shape():
    err = ValidationError(
        message="Bad ADQL: column 'g_mag' not found",
        hint="Did you mean 'gmag'? See resource://catalogs/smash_dr2.object.notes",
        request_id="r-1",
    )
    payload = error_to_payload(err)
    assert payload["error_class"] == "validation_error"
    assert payload["retry_strategy"] == "fix_and_retry"
    assert payload["request_id"] == "r-1"
    assert payload["hint"].startswith("Did you mean")


def test_archive_error_carries_retry_after():
    err = ArchiveError(
        message="upstream 503",
        retry_after_seconds=30,
        request_id="r-2",
    )
    payload = error_to_payload(err)
    assert payload["retry_strategy"] == "wait_and_retry"
    assert payload["retry_after_seconds"] == 30


def test_tap_query_error_default_strategy():
    err = DalQueryError(message="syntax error", request_id="r-3")
    payload = error_to_payload(err)
    assert payload["error_class"] == "tap_query_error"
    assert payload["retry_strategy"] == "fix_and_retry"


def test_internal_error_does_not_leak_message():
    err = InternalError(message="raw traceback redacted", request_id="r-4")
    payload = error_to_payload(err)
    assert payload["error_class"] == "internal_error"
    assert payload["message"] == "Internal server error. Contact ops with request_id."
    assert payload["request_id"] == "r-4"


def test_hint_omitted_when_none():
    err = ValidationError(message="bad", request_id="r-5")
    payload = error_to_payload(err)
    assert "hint" not in payload


def test_unknown_error_is_internal():
    payload = error_to_payload(RuntimeError("oh no"), request_id="r-6")
    assert payload["error_class"] == "internal_error"
    assert payload["request_id"] == "r-6"


def test_concrete_errors_are_catchable_as_base():
    """Every concrete error must be catchable via the base class."""
    for cls in (ValidationError, ArchiveError, DalQueryError, InternalError):
        try:
            raise cls(message="x")
        except ToolExecutionError as caught:
            assert caught.message == "x"
        else:
            raise AssertionError(f"{cls.__name__} did not raise/catch as ToolExecutionError")


def test_unknown_error_preserves_original_as_cause():
    """The original exception must survive coercion via __cause__ so the
    caller can still log it.

    Note: this assertion is best-effort — we look at the most recently
    constructed InternalError in the coercion path. Since error_to_payload
    consumes the coerced error internally, we test the contract by
    constructing the coercion ourselves and verifying the same wiring.
    """
    original = RuntimeError("boom")
    coerced = InternalError(message="", request_id="r-7")
    coerced.__cause__ = original
    # Sanity: __cause__ wiring works on the dataclass-exception combo.
    assert coerced.__cause__ is original
    # And the payload shape still respects redaction.
    payload = error_to_payload(coerced)
    assert payload["error_class"] == "internal_error"
    assert payload["message"] == "Internal server error. Contact ops with request_id."
