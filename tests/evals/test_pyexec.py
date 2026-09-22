"""PythonSession: the per-task interpreter behind the mcp arm's execute_python tool.

Real subprocesses, no network. Each test owns its session and closes it.
"""

from __future__ import annotations

import os

import pytest

from evals._pyexec import (
    DEFAULT_TIMEOUT_S,
    EXECUTE_PYTHON_TOOL,
    OUTPUT_CAP_CHARS,
    PythonSession,
)


@pytest.fixture
async def session():
    s = PythonSession()
    await s.start()
    try:
        yield s
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_state_persists_between_calls(session):
    first = await session.run("x = 41")
    assert first.error is None and first.stdout == ""
    second = await session.run("print(x + 1)")
    assert second.stdout == "42\n"
    assert second.error is None
    assert second.restarted is False
    assert second.elapsed_s >= 0


@pytest.mark.asyncio
async def test_exception_is_reported_and_stdout_kept(session):
    res = await session.run("print('before')\n1 / 0")
    assert res.stdout == "before\n"
    assert res.error is not None
    assert "ZeroDivisionError" in res.error
    # The session survives a failing snippet.
    again = await session.run("print('still alive')")
    assert again.stdout == "still alive\n"


@pytest.mark.asyncio
async def test_stderr_is_captured_separately(session):
    res = await session.run("import sys; sys.stderr.write('warn\\n'); print('out')")
    assert res.stdout == "out\n"
    assert res.stderr == "warn\n"
    assert res.error is None


@pytest.mark.asyncio
async def test_stdout_is_capped_keeping_the_tail(session):
    res = await session.run("print('a' * 20000 + 'END')")
    assert len(res.stdout) <= OUTPUT_CAP_CHARS + 60
    assert res.stdout.startswith("... [truncated:")
    assert res.stdout.rstrip().endswith("END")


@pytest.mark.asyncio
async def test_timeout_kills_and_restarts_the_session():
    s = PythonSession(timeout_s=1.0)
    await s.start()
    try:
        await s.run("marker = 1")
        res = await s.run("import time; time.sleep(5)")
        assert res.restarted is True
        assert res.error is not None and "timed out after 1 s" in res.error
        # Fresh interpreter: the old namespace is gone, but the session works.
        after = await s.run("print('marker' in globals())")
        assert after.stdout == "False\n"
        assert after.restarted is False
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_timeout_default_and_env_override(monkeypatch):
    assert PythonSession().timeout_s == DEFAULT_TIMEOUT_S == 120.0
    monkeypatch.setenv("EVAL_EXEC_TIMEOUT", "7.5")
    assert PythonSession().timeout_s == 7.5
    assert PythonSession(timeout_s=3.0).timeout_s == 3.0


@pytest.mark.asyncio
async def test_cwd_is_a_private_temp_dir_removed_on_close():
    s = PythonSession()
    await s.start()
    cwd = s.cwd
    assert cwd is not None and os.path.basename(cwd).startswith("manna-eval-")
    res = await s.run("import os; print(os.getcwd())")
    assert os.path.realpath(res.stdout.strip()) == os.path.realpath(cwd)
    await s.run("open('touch.txt', 'w').write('x')")
    assert os.path.exists(os.path.join(cwd, "touch.txt"))
    await s.close()
    assert not os.path.exists(cwd)


@pytest.mark.asyncio
async def test_sys_exit_in_snippet_does_not_kill_the_session(session):
    res = await session.run("import sys; sys.exit(3)")
    assert res.error is not None and "SystemExit" in res.error
    assert res.restarted is False
    assert (await session.run("print(1)")).stdout == "1\n"


def test_tool_schema_shape():
    assert EXECUTE_PYTHON_TOOL["name"] == "execute_python"
    schema = EXECUTE_PYTHON_TOOL["input_schema"]
    assert schema["required"] == ["code"]
    assert schema["properties"]["code"]["type"] == "string"
    desc = EXECUTE_PYTHON_TOOL["description"]
    for word in ("persistent", "fetch_recipe", "print"):
        assert word in desc
