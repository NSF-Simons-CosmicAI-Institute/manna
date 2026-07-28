from manna.errors import (
    _INTERNAL_GENERIC_MESSAGE,
    DalQueryError,
    ValidationError,
    wrap_tool_errors,
)
from manna.observability import current_request_id


def test_decorator_passthrough_on_success():
    @wrap_tool_errors
    def t():
        return {"row_count": 0, "rows": []}

    assert t() == {"row_count": 0, "rows": []}


def test_decorator_catches_tool_execution_error_and_returns_payload():
    @wrap_tool_errors
    def t():
        raise DalQueryError(message="bad ADQL")

    out = t()
    assert out["error_class"] == "tap_query_error"
    assert out["message"] == "bad ADQL"
    assert out["retry_strategy"] == "fix_and_retry"
    assert "isError" not in out


def test_decorator_coerces_unknown_exception_to_internal_error():
    @wrap_tool_errors
    def t():
        raise RuntimeError("upstream blew up")

    out = t()
    assert out["error_class"] == "internal_error"
    # InternalError redacts the message
    assert out["message"] == _INTERNAL_GENERIC_MESSAGE


def test_decorator_threads_request_id_from_contextvar():
    @wrap_tool_errors
    def t():
        raise ValidationError(message="bad")

    token = current_request_id.set("test-req-id-123")
    try:
        out = t()
    finally:
        current_request_id.reset(token)

    assert out["request_id"] == "test-req-id-123"


def test_decorator_logger_name_includes_function_name(caplog):
    @wrap_tool_errors
    def vo_thing():
        raise DalQueryError(message="x")

    with caplog.at_level("WARNING", logger="manna.tools.vo_thing"):
        vo_thing()
    # At least one record should be on the per-function logger
    matching = [r for r in caplog.records if r.name == "manna.tools.vo_thing"]
    assert matching, "expected a WARNING log on logger 'manna.tools.vo_thing'"
    assert matching[0].levelname == "WARNING"
