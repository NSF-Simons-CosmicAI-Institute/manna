"""_result_payload must flag the server's error-as-payload contract.

MCP tools return errors as normal results discriminated by `error_class`
(never MCP isError) — the harness has to detect that, or the mcp arm
reports 0 tool errors by construction.
"""

from types import SimpleNamespace

from evals.harness import _result_payload


def _result(structured=None, is_error=False):
    return SimpleNamespace(is_error=is_error, structured_content=structured, content=None)


def test_error_class_payload_counts_as_error():
    payload, is_error = _result_payload(
        _result(
            {"error_class": "archive_error", "message": "x", "retry_strategy": "wait_and_retry"}
        )
    )
    assert is_error is True
    assert payload["error_class"] == "archive_error"


def test_ok_payload_is_not_error():
    _, is_error = _result_payload(_result({"row_count": 3, "truncated": False}))
    assert is_error is False


def test_mcp_is_error_flag_still_respected():
    _, is_error = _result_payload(_result({"text": "boom"}, is_error=True))
    assert is_error is True
