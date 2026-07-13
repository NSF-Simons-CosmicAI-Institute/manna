"""ACP-persona drivers — the *harness* axis of the Pillar-2 matrix.

Instead of our custom agent loop (harness.run_task), a persona driver runs a REAL agent
framework end-to-end against the MCP server and parses its transcript into the same
`TaskRun`, so the exact same scoring (ground-truth / rubric / judge) applies. This is the
scored generalization of deploy/frontend/.../smoke-test.sh.

First driver: **Claude Code** (`claude -p --output-format stream-json`). The MCP server is
passed inline via --mcp-config (+ --strict-mcp-config to ignore any global/project config),
and the persona's model is whatever `claude` is authed with — override via `PersonaConfig.env`
(ANTHROPIC_BASE_URL/…) to drive it against the same local model as the custom loop for a
clean harness-vs-harness comparison.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from evals.harness import TaskRun, ToolCall

_MCP_SERVER_NAME = "astro-archives"
_MCP_PREFIX = f"mcp__{_MCP_SERVER_NAME}__"


@dataclass
class PersonaConfig:
    label: str = "claude-code"
    model: str | None = None  # --model override (else the persona's default)
    env: dict[str, str] = field(default_factory=dict)  # extra env (e.g. point at Qwen)
    cwd: str | None = None  # neutral working dir so it doesn't inherit a repo's CLAUDE.md


class Persona(Protocol):
    """A real agent harness driven end-to-end against the MCP server.

    Implementations run a framework's CLI/SDK on the task's prompt with the MCP server
    attached, then parse its transcript into a `TaskRun` so the shared scoring applies.
    """

    cfg: PersonaConfig

    async def run(self, task: dict[str, Any], mcp_url: str) -> TaskRun: ...


def _tool_name(raw: str) -> str:
    """Normalize an MCP tool to its bare vo_* name so it matches arg-checks/breakdown;
    leave harness built-ins (ToolSearch, Bash, …) as-is."""
    return raw[len(_MCP_PREFIX) :] if raw.startswith(_MCP_PREFIX) else raw


def _parse_stream_json(task: dict[str, Any], stdout: str, label: str) -> TaskRun:
    run = TaskRun(task["id"], task["tier"], "full", label, arm="claude-code")
    uses: dict[str, dict[str, Any]] = {}  # tool_use_id -> {name, input}
    results: dict[str, dict[str, Any]] = {}  # tool_use_id -> {content, is_error}
    order: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = e.get("type")
        if etype == "assistant":
            for b in e.get("message", {}).get("content", []):
                if b.get("type") == "tool_use":
                    uses[b["id"]] = {"name": _tool_name(b["name"]), "input": b.get("input") or {}}
                    order.append(b["id"])
        elif etype == "user":
            for b in e.get("message", {}).get("content", []):
                if b.get("type") == "tool_result":
                    results[b["tool_use_id"]] = {
                        "content": b.get("content"),
                        "is_error": bool(b.get("is_error")),
                    }
        elif etype == "result":
            run.final_answer = (e.get("result") or "").strip()
            run.steps = e.get("num_turns") or 0
            run.latency_s = (e.get("duration_ms") or 0) / 1000
            u = e.get("usage") or {}
            run.input_tokens = u.get("input_tokens", 0)
            run.output_tokens = u.get("output_tokens", 0)
            if e.get("is_error"):
                run.error = f"persona result is_error (stop_reason={e.get('stop_reason')})"

    for tid in order:
        use = uses[tid]
        res = results.get(tid, {})
        run.trace.append(
            ToolCall(
                use["name"], dict(use["input"]), res.get("content"), res.get("is_error", False)
            )
        )
    if not run.final_answer and not run.error:
        run.error = "persona produced no result event"
    return run


class ClaudeCodePersona:
    """Drive Claude Code headless against the MCP server."""

    def __init__(self, cfg: PersonaConfig | None = None):
        self.cfg = cfg or PersonaConfig()

    async def run(self, task: dict[str, Any], mcp_url: str) -> TaskRun:
        mcp_config = json.dumps(
            {"mcpServers": {_MCP_SERVER_NAME: {"type": "http", "url": mcp_url}}}
        )
        cmd = [
            "claude",
            "-p",
            task["prompt"],
            "--output-format",
            "stream-json",
            "--verbose",
            "--mcp-config",
            mcp_config,
            "--strict-mcp-config",
            "--dangerously-skip-permissions",
        ]
        if self.cfg.model:
            cmd += ["--model", self.cfg.model]
        env = {**os.environ, **self.cfg.env}
        # When redirecting to a custom model endpoint, drop inherited creds that would
        # otherwise win over (or collide with) the endpoint's own auth.
        if self.cfg.env.get("ANTHROPIC_BASE_URL"):
            for k in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN"):
                env.pop(k, None)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cfg.cwd,
                env=env,
            )
            out, err = await proc.communicate()
        except Exception as exc:
            r = TaskRun(task["id"], task["tier"], "full", self.cfg.label, arm="claude-code")
            r.error = f"persona launch failed: {type(exc).__name__}: {exc}"
            return r
        run = _parse_stream_json(task, out.decode("utf-8", "replace"), self.cfg.label)
        if proc.returncode != 0 and not run.error:
            run.error = f"claude exited {proc.returncode}: {err.decode('utf-8', 'replace')[:200]}"
        return run


# Registry of available harness drivers. Only Claude Code is shipped — it is the one agent
# CLI installed and validated here. To add another (Gemini CLI, Goose, …), implement the
# `Persona` protocol and register it below; persona_run.py picks it up by name, no other edit.
PERSONA_REGISTRY: dict[str, type] = {
    "claude-code": ClaudeCodePersona,
}


def make_persona(name: str, cfg: PersonaConfig) -> Persona:
    """Build a persona by registry name, or raise with the list of what's available."""
    try:
        cls = PERSONA_REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(PERSONA_REGISTRY))
        raise ValueError(f"unknown persona {name!r}; available: {available}") from None
    return cls(cfg)
