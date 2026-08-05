"""Offline unit tests for harness config plumbing (evals/harness.py):
ModelConfig.from_env inheritance rules, custom-header parsing, env knobs, TaskRun."""

from __future__ import annotations

from evals.harness import (
    ModelConfig,
    TaskRun,
    ToolCall,
    _max_steps,
    _parse_custom_headers,
    _poll_sleep,
)

_MODEL_VARS = (
    "EVAL_MODEL_NAME",
    "EVAL_MODEL_BASE_URL",
    "EVAL_MODEL_API_KEY",
    "EVAL_MODEL_CUSTOM_HEADERS",
    "EVAL_MODEL_LABEL",
    "EVAL_MODEL_BACKEND",
    "EVAL_JUDGE_NAME",
    "EVAL_JUDGE_BASE_URL",
    "EVAL_JUDGE_API_KEY",
    "EVAL_JUDGE_BACKEND",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "EVAL_MAX_STEPS",
    "EVAL_ASYNC_POLL_SLEEP",
)


def _clear(monkeypatch):
    for v in _MODEL_VARS:
        monkeypatch.delenv(v, raising=False)


def test_parse_custom_headers():
    h = _parse_custom_headers("Authorization: Basic abc; X-Extra: v2")
    assert h == {"Authorization": "Basic abc", "X-Extra": "v2"}
    assert _parse_custom_headers("") == {}
    assert _parse_custom_headers("garbage-no-colon") == {}


def test_from_env_model_reads_own_vars(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("EVAL_MODEL_NAME", "example/model-a")
    monkeypatch.setenv("EVAL_MODEL_BASE_URL", "https://proxy/mcp")
    monkeypatch.setenv("EVAL_MODEL_BACKEND", "openai")
    cfg = ModelConfig.from_env()
    assert cfg.model == "example/model-a"
    assert cfg.base_url == "https://proxy/mcp"
    assert cfg.backend == "openai"


def test_from_env_model_inherits_anthropic_vars(monkeypatch):
    _clear(monkeypatch)
    # no EVAL_MODEL_* → EVAL_MODEL falls back to ANTHROPIC_*
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://inherited")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_OPUS_MODEL", "claude-opus-4-8")
    cfg = ModelConfig.from_env("EVAL_MODEL")
    assert cfg.base_url == "https://inherited"
    assert cfg.model == "claude-opus-4-8"


def test_from_env_judge_does_not_inherit_anthropic(monkeypatch):
    """The judge must stay isolated — no ANTHROPIC_* leak (else a Basic-auth proxy header
    or base_url would bleed into a hosted-Claude judge)."""
    _clear(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy-should-not-leak")
    monkeypatch.setenv("EVAL_JUDGE_NAME", "claude-haiku-4-5")
    cfg = ModelConfig.from_env("EVAL_JUDGE")
    assert cfg.model == "claude-haiku-4-5"
    assert cfg.base_url is None  # did NOT inherit ANTHROPIC_BASE_URL


def test_backend_defaults_to_anthropic(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("EVAL_MODEL_NAME", "m")
    assert ModelConfig.from_env().backend == "anthropic"


def test_env_knobs(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("EVAL_MAX_STEPS", "7")
    monkeypatch.setenv("EVAL_ASYNC_POLL_SLEEP", "2.5")
    assert _max_steps() == 7
    assert _poll_sleep() == 2.5


def test_taskrun_num_tool_calls_and_to_dict():
    r = TaskRun("mq-x", 2, "full", "model-a", arm="mcp")
    r.trace = [ToolCall("vo_a", {"k": 1}, {"ok": True}, False), ToolCall("vo_b", {}, None, True)]
    r.final_answer = "done"
    r.input_tokens, r.output_tokens = 10, 3
    assert r.num_tool_calls == 2
    d = r.to_dict()
    assert d["task_id"] == "mq-x"
    assert d["arm"] == "mcp"
    assert d["num_tool_calls"] == 2
    assert d["tokens"] == {"input": 10, "output": 3}
