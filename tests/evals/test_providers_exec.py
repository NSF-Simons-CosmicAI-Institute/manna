"""execute_python is an mcp-arm-only tool served by the harness, not by MANNA."""

from __future__ import annotations

import pytest

from evals.providers import (
    MCPToolProvider,
    RawTapToolProvider,
    RawWebToolProvider,
    make_provider,
)


def _names(provider) -> list[str]:
    return [t["name"] for t in provider.tools]


@pytest.mark.asyncio
async def test_mcp_arm_lists_execute_python_by_default():
    async with MCPToolProvider() as p:
        names = _names(p)
    assert names[-1] == "execute_python"
    assert "run_adql_query" in names  # the MANNA tools are still all there


@pytest.mark.asyncio
async def test_mcp_arm_can_opt_out():
    async with MCPToolProvider(exec_tool=False) as p:
        assert "execute_python" not in _names(p)


@pytest.mark.asyncio
async def test_execute_python_is_served_without_touching_the_mcp_client(monkeypatch):
    async with MCPToolProvider() as p:

        async def _boom(*a, **k):
            raise AssertionError("execute_python must not reach the MCP client")

        monkeypatch.setattr(p._client, "call_tool", _boom)
        payload, is_error = await p.call("execute_python", {"code": "print('hi')"})
    assert is_error is False
    assert payload["stdout"] == "hi\n"
    assert payload["error"] is None
    assert set(payload) == {"stdout", "stderr", "error", "elapsed_s", "restarted"}


@pytest.mark.asyncio
async def test_execute_python_error_sets_is_error():
    async with MCPToolProvider() as p:
        payload, is_error = await p.call("execute_python", {"code": "1/0"})
    assert is_error is True
    assert "ZeroDivisionError" in payload["error"]


@pytest.mark.asyncio
async def test_session_is_closed_on_exit():
    p = MCPToolProvider()
    async with p:
        cwd = p._session.cwd
        assert cwd is not None
    import os

    assert not os.path.exists(cwd)
    assert p._session is None


@pytest.mark.asyncio
async def test_raw_arms_are_unchanged():
    for cls, expected in ((RawTapToolProvider, ["run_adql"]), (RawWebToolProvider, ["http_get"])):
        async with cls() as p:
            assert _names(p) == expected


def test_make_provider_passes_exec_tool_through():
    assert make_provider("mcp", exec_tool=False)._exec_tool is False
    assert make_provider("mcp")._exec_tool is True
    assert not hasattr(make_provider("raw_tap"), "_exec_tool")
