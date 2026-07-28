"""Offline unit tests for the persona layer (evals/personas.py) — transcript parsing,
tool-name normalization, and the registry. No subprocess is spawned."""

from __future__ import annotations

import json

import pytest

from evals.personas import (
    ClaudeCodePersona,
    PersonaConfig,
    _parse_stream_json,
    _tool_name,
    make_persona,
)

_TASK = {"id": "mq-coords-m87", "tier": 1}


def test_tool_name_strips_mcp_prefix_only():
    assert _tool_name("mcp__manna__vo_target_resolve") == "vo_target_resolve"
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
                        "name": "mcp__manna__vo_target_resolve",
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
    assert call.tool == "vo_target_resolve"  # normalized
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
