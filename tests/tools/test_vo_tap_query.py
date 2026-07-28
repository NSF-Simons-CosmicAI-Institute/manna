"""End-to-end integration test for vo_tap_query through an in-memory MCP client.

The test mounts the real FastMCP server (via the ``mcp_server`` fixture) and
talks to it with ``fastmcp.Client``. Network traffic is recorded with vcrpy.
"""

import pytest
from fastmcp import Client

from manna.errors import DalQueryError, ValidationError
from manna.tools import tap as ivoa_tools


@pytest.mark.vcr
async def test_vo_tap_query_via_in_memory_client(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_tap_query",
            {
                "endpoint": "https://datalab.noirlab.edu/tap",
                "adql": (
                    "SELECT TOP 3 ra, dec FROM smash_dr2.object "
                    "WHERE ra BETWEEN 185 AND 185.01 ORDER BY ra"
                ),
                "maxrec": 10,
            },
        )
        payload = result.structured_content
        assert payload["row_count"] <= 3
        assert payload["truncated"] is False
        assert payload["archive"] == "datalab"
        names = {c["name"] for c in payload["columns"]}
        assert {"ra", "dec"}.issubset(names)


async def test_vo_tap_query_validation_error_surface(mcp_server):
    async with Client(mcp_server) as client:
        # raise_on_error=False so we can inspect the surfaced error shape
        # rather than catching the framework-level ToolError exception.
        result = await client.call_tool(
            "vo_tap_query",
            {
                "endpoint": "https://datalab.noirlab.edu/tap",
                "adql": "SELECT TOP 3 ra FROM x",
                "maxrec": -1,  # violates Field(ge=1)
            },
            raise_on_error=False,
        )
        # FastMCP 3.3.1 surfaces Pydantic validation as a framework-level tool
        # error: is_error=True with the message in result.content (TextContent).
        # If a future version starts shipping our error payload through
        # structured_content instead, the discriminator is `error_class`.
        if result.is_error:
            content_text = "".join(getattr(c, "text", "") for c in result.content)
            assert "maxrec" in content_text
        else:
            payload = result.structured_content
            assert payload.get("error_class") is not None


class _FakeTap:
    def __init__(self, exc):
        self._exc = exc

    def query(self, **_kw):
        raise self._exc


@pytest.mark.parametrize(
    ("exc", "expected_error_class"),
    [
        (DalQueryError(message="column not found"), "tap_query_error"),
        (ValidationError(message="bad endpoint", hint="see docs"), "validation_error"),
        (RuntimeError("upstream blew up"), "internal_error"),
    ],
)
def test_vo_tap_query_error_path_returns_structured_payload(exc, expected_error_class, monkeypatch):
    """When the backend raises, vo_tap_query returns a structured payload
    keyed on ``error_class`` (NOT ``isError``). The protocol-level
    ``is_error`` flag is FastMCP's separate concern.
    """
    monkeypatch.setattr(ivoa_tools, "_get_tap", lambda: _FakeTap(exc))
    payload = ivoa_tools.vo_tap_query(
        endpoint="https://datalab.noirlab.edu/tap",
        adql="SELECT 1",
        maxrec=10,
    )
    assert "isError" not in payload, (
        "isError key should not be in the payload (see ivoa.py docstring)"
    )
    assert payload["error_class"] == expected_error_class
    assert "retry_strategy" in payload


# --------------------------------------------------------------------------- #
# the shipped few-shot example must not teach a trap
#
# The old example ran CONTAINS(POINT(...)) against smash_dr2.object, a Data Lab
# table. Verified live 2026-07-15: it fails with
#   "function point(unknown, double precision, double precision) does not exist"
# — the exact construct datalab.py's geometry-contains-untranslated note
# documents as broken and tasks.yaml's t3-datalab-geometry docks models for
# emitting. The Field description is re-sent to the model on EVERY turn, so we
# taught the trap continuously and then penalized the model for copying us.
# --------------------------------------------------------------------------- #
def _adql_field_examples() -> list[str]:
    """The `examples` the model actually sees on vo_tap_query's adql parameter."""
    import inspect

    from manna.tools.tap import vo_tap_query

    param = inspect.signature(vo_tap_query).parameters["adql"]
    field = param.annotation.__metadata__[0]
    return list(field.examples or [])


def _datalab_examples() -> list[str]:
    return [e for e in _adql_field_examples() if "smash_dr2" in e or "nsc_dr2" in e]


def test_datalab_example_does_not_teach_the_geometry_trap():
    examples = _datalab_examples()
    assert examples, "expected at least one Data Lab example"
    for example in examples:
        assert "CONTAINS(" not in example.upper()
        assert "POINT(" not in example.upper()


def test_datalab_example_uses_the_verified_q3c_form():
    assert any("q3c_radial_query" in e and "= 't'" in e for e in _datalab_examples()), (
        "Data Lab cones need q3c_radial_query(...) = 't' — the = 't' literal is required"
    )


def test_an_example_still_shows_standard_geometry_for_obscore():
    """CONTAINS genuinely works on obscore services — don't overcorrect into
    teaching that ADQL geometry is universally broken."""
    obscore = [e for e in _adql_field_examples() if "obscore" in e.lower()]
    assert obscore, "expected an obscore example"
    assert any("CONTAINS(" in e.upper() for e in obscore)
