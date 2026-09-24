"""Offline unit tests for the persona layer (evals/personas.py) — transcript parsing,
tool-name normalization, and the registry. No subprocess is spawned."""

from __future__ import annotations

import asyncio
import json

import pytest

from evals import personas as personas_mod
from evals.personas import (
    ClaudeCodePersona,
    PersonaConfig,
    _parse_stream_json,
    _tool_name,
    make_persona,
)

_TASK = {"id": "mq-coords-m87", "tier": 1, "prompt": "resolve M87"}


def test_tool_name_strips_mcp_prefix_only():
    assert _tool_name("mcp__manna__resolve_target_name") == "resolve_target_name"
    assert _tool_name("Bash") == "Bash"  # harness built-ins pass through
    assert _tool_name("ToolSearch") == "ToolSearch"


def _stream(*events):
    return "\n".join(json.dumps(e) for e in events)


def test_parse_stream_json_full_transcript():
    stdout = _stream(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "a",
                        "name": "mcp__manna__resolve_target_name",
                        "input": {"name": "M87"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "a",
                        "content": '{"ra":187.7}',
                        "is_error": False,
                    }
                ]
            },
        },
        {
            "type": "result",
            "result": "M87 is at RA 187.7",
            "num_turns": 2,
            "duration_ms": 3400,
            "usage": {"input_tokens": 100, "output_tokens": 20},
        },
    )
    run = _parse_stream_json(_TASK, stdout, "claude-code")
    assert run.arm == "claude-code"
    assert len(run.trace) == 1
    call = run.trace[0]
    assert call.tool == "resolve_target_name"  # normalized
    assert call.args == {"name": "M87"}
    assert call.is_error is False
    assert run.final_answer == "M87 is at RA 187.7"
    assert run.steps == 2
    assert run.latency_s == 3.4
    assert run.input_tokens == 100
    assert run.output_tokens == 20
    assert run.error is None


def test_parse_stream_json_missing_result_is_error():
    stdout = _stream(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "thinking"}]}}
    )
    run = _parse_stream_json(_TASK, stdout, "claude-code")
    assert run.error is not None
    assert "no result" in run.error


def test_parse_stream_json_result_is_error_flag():
    stdout = _stream(
        {
            "type": "result",
            "result": "",
            "is_error": True,
            "stop_reason": "max_turns",
            "num_turns": 9,
        }
    )
    run = _parse_stream_json(_TASK, stdout, "claude-code")
    assert run.error is not None
    assert "max_turns" in run.error


def test_parse_stream_json_ignores_non_json_lines():
    stdout = "not json\n" + _stream({"type": "result", "result": "ok", "num_turns": 1})
    run = _parse_stream_json(_TASK, stdout, "cc")
    assert run.final_answer == "ok"


def test_parse_stream_json_totals_cache_tokens_and_cost():
    stdout = _stream(
        {
            "type": "result",
            "result": "ok",
            "num_turns": 1,
            "usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 9007,
                "cache_read_input_tokens": 13613,
                "output_tokens": 29,
            },
            "total_cost_usd": 0.0976515,
            "modelUsage": {"claude-opus-4-8": {"inputTokens": 10}},
        }
    )
    run = _parse_stream_json(_TASK, stdout, "claude-code")
    assert run.input_tokens == 22630  # 10 + 9007 + 13613 (uncached + cache write + cache read)
    assert run.output_tokens == 29
    assert run.cost_usd == 0.0976515
    assert run.persona_model == "claude-opus-4-8"


def test_parse_stream_json_persona_model_ignores_haiku_side_call():
    """Claude Code bills a small Haiku side-call (title/classification) and lists it FIRST
    in modelUsage; the label must name the model that did the work, not the first key.
    Observed 2026-09-23: a --model claude-sonnet-5 run labelled claude-haiku-4-5-20251001."""
    stdout = _stream(
        {
            "type": "result",
            "result": "ok",
            "num_turns": 1,
            "total_cost_usd": 0.0603,
            "modelUsage": {
                "claude-haiku-4-5-20251001": {
                    "inputTokens": 898,
                    "outputTokens": 9,
                    "costUSD": 0.0009,
                },
                "claude-sonnet-5": {"inputTokens": 2, "outputTokens": 4, "costUSD": 0.0594},
            },
        }
    )
    run = _parse_stream_json(_TASK, stdout, "claude-code")
    assert run.persona_model == "claude-sonnet-5"


def test_parse_stream_json_missing_usage_leaves_cost_and_model_none():
    stdout = _stream({"type": "result", "result": "ok", "num_turns": 1})
    run = _parse_stream_json(_TASK, stdout, "claude-code")
    assert run.input_tokens == 0
    assert run.cost_usd is None
    assert run.persona_model is None


# --------------------------------------------------------------------------- #
# ClaudeCodePersona.run — command construction, isolation, timeout
# --------------------------------------------------------------------------- #
class _FakeProc:
    """Stand-in for asyncio.subprocess.Process: communicate()/kill()/wait()/returncode."""

    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", sleep_s: float | None = None):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = 0
        self._sleep_s = sleep_s
        self.killed = False
        self.waited = False

    async def communicate(self):
        if self._sleep_s is not None:
            await asyncio.sleep(self._sleep_s)
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True
        return self.returncode


def _flag_value(cmd, flag):
    cmd = list(cmd)
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


_OK_STDOUT = b'{"type":"result","result":"x","num_turns":1}\n'


async def test_run_isolates_and_caps_turns_by_default(monkeypatch):
    monkeypatch.delenv("EVAL_MAX_STEPS", raising=False)
    captured = {}

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc(stdout=_OK_STDOUT)

    monkeypatch.setattr(personas_mod.asyncio, "create_subprocess_exec", fake_exec)
    persona = ClaudeCodePersona(PersonaConfig(label="x"))
    await persona.run(_TASK, "http://127.0.0.1:9/mcp")
    cmd = captured["cmd"]
    assert _flag_value(cmd, "--setting-sources") == ""
    assert "--no-session-persistence" in cmd
    assert _flag_value(cmd, "--max-turns") == "20"


async def test_run_appends_system_prompt_only_when_set(monkeypatch):
    captured = {}

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc(stdout=_OK_STDOUT)

    monkeypatch.setattr(personas_mod.asyncio, "create_subprocess_exec", fake_exec)
    await ClaudeCodePersona(PersonaConfig(label="x", system_prompt="Use the tools.")).run(
        _TASK, "http://127.0.0.1:9/mcp"
    )
    assert _flag_value(captured["cmd"], "--append-system-prompt") == "Use the tools."
    await ClaudeCodePersona(PersonaConfig(label="x")).run(_TASK, "http://127.0.0.1:9/mcp")
    assert "--append-system-prompt" not in captured["cmd"]


async def test_run_no_isolate_omits_isolation_flags(monkeypatch):
    captured = {}

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc(stdout=_OK_STDOUT)

    monkeypatch.setattr(personas_mod.asyncio, "create_subprocess_exec", fake_exec)
    persona = ClaudeCodePersona(PersonaConfig(label="x", isolate=False))
    await persona.run(_TASK, "http://127.0.0.1:9/mcp")
    cmd = captured["cmd"]
    assert "--setting-sources" not in cmd
    assert "--no-session-persistence" not in cmd


async def test_run_without_mcp_passes_empty_strict_config_and_raw_arm(monkeypatch):
    """The without-MANNA approach: no MANNA server in --mcp-config, but --strict-mcp-config
    is KEPT with an empty server map so a developer's global MCP servers cannot leak in."""
    captured = {}

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc(stdout=_OK_STDOUT)

    monkeypatch.setattr(personas_mod.asyncio, "create_subprocess_exec", fake_exec)
    run = await ClaudeCodePersona(PersonaConfig(label="x", mcp=False)).run(
        _TASK, "http://127.0.0.1:9/mcp"
    )
    cmd = captured["cmd"]
    assert json.loads(_flag_value(cmd, "--mcp-config")) == {"mcpServers": {}}
    assert "--strict-mcp-config" in cmd
    assert run.arm == "claude-code-raw"


async def test_run_with_mcp_names_manna_server_and_default_arm(monkeypatch):
    captured = {}

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc(stdout=_OK_STDOUT)

    monkeypatch.setattr(personas_mod.asyncio, "create_subprocess_exec", fake_exec)
    run = await ClaudeCodePersona(PersonaConfig(label="x")).run(_TASK, "http://127.0.0.1:9/mcp")
    cfg = json.loads(_flag_value(captured["cmd"], "--mcp-config"))
    assert cfg["mcpServers"]["manna"]["url"] == "http://127.0.0.1:9/mcp"
    assert run.arm == "claude-code"


async def test_run_records_condition_on_every_task_run(monkeypatch):
    async def fake_exec(*cmd, **kwargs):
        return _FakeProc(stdout=_OK_STDOUT)

    monkeypatch.setattr(personas_mod.asyncio, "create_subprocess_exec", fake_exec)
    run = await ClaudeCodePersona(PersonaConfig(label="x", condition="ablated")).run(
        _TASK, "http://127.0.0.1:9/mcp"
    )
    assert run.condition == "ablated"
    run = await ClaudeCodePersona(PersonaConfig(label="x")).run(_TASK, "http://127.0.0.1:9/mcp")
    assert run.condition == "full"


async def test_run_honors_max_turns_override(monkeypatch):
    captured = {}

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc(stdout=_OK_STDOUT)

    monkeypatch.setattr(personas_mod.asyncio, "create_subprocess_exec", fake_exec)
    persona = ClaudeCodePersona(PersonaConfig(label="x", max_turns=7))
    await persona.run(_TASK, "http://127.0.0.1:9/mcp")
    assert _flag_value(captured["cmd"], "--max-turns") == "7"


async def test_run_times_out_and_kills_process(monkeypatch):
    proc_holder = {}

    async def fake_exec(*cmd, **kwargs):
        proc = _FakeProc(sleep_s=5)
        proc_holder["proc"] = proc
        return proc

    monkeypatch.setattr(personas_mod.asyncio, "create_subprocess_exec", fake_exec)
    persona = ClaudeCodePersona(PersonaConfig(label="x", timeout_s=0.2))
    run = await persona.run(_TASK, "http://127.0.0.1:9/mcp")
    assert run.error is not None
    assert "timed out after 0.2 s" in run.error
    assert proc_holder["proc"].killed is True
    assert proc_holder["proc"].waited is True


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #
def test_make_persona_builds_claude_code():
    p = make_persona("claude-code", PersonaConfig(label="x"))
    assert isinstance(p, ClaudeCodePersona)
    assert p.cfg.label == "x"


def test_make_persona_unknown_raises_with_available():
    with pytest.raises(ValueError) as exc:
        make_persona("gemini", PersonaConfig())
    assert "claude-code" in str(exc.value)  # lists what's available


def test_persona_run_suites_resolve_to_existing_task_files():
    from evals.persona_run import SUITES
    from evals.score import load_tasks

    assert set(SUITES) == {"mcp-quality", "tiers"}
    for path in SUITES.values():
        assert path.exists(), path
    tiers = load_tasks(SUITES["tiers"])
    assert {t["tier"] for t in tiers} == {1, 2, 3, 4}
    assert all("expect_tools" in t or "expect_any_of" in t or "rubric" in t for t in tiers)


def test_parse_stream_json_drops_client_persisted_path_but_keeps_the_fact():
    """Claude Code swaps an oversize MCP result for a note carrying a LOCAL path; the
    trace must record that it happened without the client's path (which the tier-4 leak
    scan would otherwise flag as a MANNA leak)."""
    persisted = (
        "<persisted-output>\nOutput too large (68KB). Full output saved to: "
        "/Users/someone/.claude/projects/x/tool-results/abc.txt\n\nPreview (first 2KB):\n{...}"
    )
    stdout = _stream(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "mcp__manna__search_ivoa_registry",
                        "input": {"keywords": ["CADC"]},
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": persisted}]
            },
        },
        {"type": "result", "result": "ok", "num_turns": 2},
    )
    run = _parse_stream_json(_TASK, stdout, "claude-code")
    assert run.trace[0].tool == "search_ivoa_registry"
    assert "/Users/" not in json.dumps(run.trace[0].result)
    assert "persisted oversize tool result (68KB)" in json.dumps(run.trace[0].result)


def test_leak_scan_covers_manna_results_only():
    from evals.harness import TaskRun, ToolCall
    from evals.score import _leaked

    run = TaskRun("t", 4, "full", "x", arm="claude-code")
    run.trace.append(ToolCall("Bash", {"command": "which python3"}, "/Users/me/bin/python3", False))
    assert _leaked(run) is None
    run.trace.append(ToolCall("list_archives", {}, "Traceback (most recent call last)", False))
    assert _leaked(run) == "Traceback (most recent call last)"
