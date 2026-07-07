"""Agent loop: drive a real LLM through the MCP tools and record the trace.

Model calls go to the configured Anthropic-Messages endpoint (the dlai01 vLLM
Qwen3.5 by default — the same endpoint the Jupyter AI persona uses). Tool calls
execute against an in-memory ``Client(build_mcp())`` with **live network** to the
real archives (the eval measures real correctness, so no cassettes here).

The full structured trace — ordered (tool, args, result) plus the final answer —
is what ``score.py`` grades against ``tasks.yaml``.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastmcp import Client

from astro_archives_mcp.app import build_mcp
from evals.context import ablated_context, full_context

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

# Rounds of (assistant -> tool calls -> results) before we give up on a task.
# Async TAP lifecycles poll vo_tap_status repeatedly, so this must be generous.
MAX_STEPS = 20
DEFAULT_MAX_TOKENS = 4096

# When a status poll comes back non-terminal, wait before handing control back to
# the model so the upstream job actually has wall-clock time to progress — otherwise
# the model burns its whole step budget on back-to-back polls of a QUEUED job.
ASYNC_POLL_SLEEP_S = 6.0
_NONTERMINAL_PHASES = {"PENDING", "QUEUED", "EXECUTING", "HELD", "SUSPENDED", "UNKNOWN"}

# Cap the size of a single tool result fed back to the model. A large
# vo_registry_describe / preview payload can otherwise blow the model's context
# window in one shot. The FULL result is still recorded in the trace for scoring;
# only what the model sees is trimmed (a real client would manage context too).
MAX_TOOL_RESULT_CHARS = 24000

SYSTEM_PROMPT = (
    "You are an assistant for professional astronomers with access to a set of "
    "Virtual Observatory tools for querying astronomical archives. Use the tools "
    "to answer the user's request rather than answering from memory. When you "
    "report sky coordinates, give them in decimal degrees (ICRS). When you report "
    "a count, state the integer explicitly. Finish with a concise final answer."
)


@dataclass
class ModelConfig:
    """How to reach the model under test (Anthropic Messages API compatible)."""

    model: str
    base_url: str | None = None
    api_key: str = "dummy"
    extra_headers: dict[str, str] = field(default_factory=dict)
    max_tokens: int = DEFAULT_MAX_TOKENS
    label: str = "model"

    @classmethod
    def from_env(cls, prefix: str = "EVAL_MODEL") -> ModelConfig:
        """Build from env, falling back to the persona's ``ANTHROPIC_*`` vars so
        the same ``deploy/frontend/.env`` that runs the persona also runs the eval.

        Recognized (prefix defaults to EVAL_MODEL):
          {PREFIX}_NAME / ANTHROPIC_DEFAULT_OPUS_MODEL  -> served model name
          {PREFIX}_BASE_URL / ANTHROPIC_BASE_URL        -> endpoint (omit for hosted)
          {PREFIX}_API_KEY / ANTHROPIC_API_KEY          -> auth token (dummy for vLLM)
          ANTHROPIC_CUSTOM_HEADERS                      -> "Header: v; Header2: v2"
        """
        name = (
            os.getenv(f"{prefix}_NAME")
            or os.getenv("ANTHROPIC_DEFAULT_OPUS_MODEL")
            or "claude-opus-4-8"
        )
        base_url = os.getenv(f"{prefix}_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL")
        api_key = os.getenv(f"{prefix}_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or "dummy"
        headers = _parse_custom_headers(os.getenv("ANTHROPIC_CUSTOM_HEADERS", ""))
        return cls(
            model=name,
            base_url=base_url or None,
            api_key=api_key,
            extra_headers=headers,
            label=os.getenv(f"{prefix}_LABEL", name),
        )

    def client(self) -> AsyncAnthropic:
        from anthropic import AsyncAnthropic

        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        if self.extra_headers:
            kwargs["default_headers"] = self.extra_headers
        return AsyncAnthropic(**kwargs)


def _parse_custom_headers(raw: str) -> dict[str, str]:
    """Parse ``ANTHROPIC_CUSTOM_HEADERS`` ("Name: value; Name2: value2")."""
    headers: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, _, value = part.partition(":")
        headers[name.strip()] = value.strip()
    return headers


@dataclass
class ToolCall:
    tool: str
    args: dict[str, Any]
    result: Any
    is_error: bool


@dataclass
class TaskRun:
    """Everything score.py needs about one task execution."""

    task_id: str
    tier: int
    condition: str  # "full" | "ablated"
    model: str
    trace: list[ToolCall] = field(default_factory=list)
    final_answer: str = ""
    steps: int = 0
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None  # harness-level failure (not a tool error)
    async_incomplete: bool = False  # ran out of budget polling a live async job

    @property
    def num_tool_calls(self) -> int:
        return len(self.trace)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "tier": self.tier,
            "condition": self.condition,
            "model": self.model,
            "final_answer": self.final_answer,
            "num_tool_calls": self.num_tool_calls,
            "steps": self.steps,
            "latency_s": round(self.latency_s, 2),
            "tokens": {"input": self.input_tokens, "output": self.output_tokens},
            "error": self.error,
            "async_incomplete": self.async_incomplete,
            "trace": [
                {
                    "tool": c.tool,
                    "args": c.args,
                    "is_error": c.is_error,
                    "result": c.result,
                }
                for c in self.trace
            ],
        }


def _anthropic_tools(mcp_tools) -> list[dict[str, Any]]:
    """Convert FastMCP tool descriptors to Anthropic tool-use format."""
    out = []
    for t in mcp_tools:
        out.append(
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema or {"type": "object", "properties": {}},
            }
        )
    return out


def _result_payload(result) -> tuple[Any, bool]:
    """Extract a JSON-able payload + error flag from a FastMCP call result."""
    is_error = bool(getattr(result, "is_error", False))
    payload = getattr(result, "structured_content", None)
    if payload is None:
        # Fall back to concatenated text content blocks.
        blocks = getattr(result, "content", None) or []
        texts = [getattr(b, "text", "") for b in blocks]
        payload = {"text": "".join(texts)}
    return payload, is_error


def _tool_result_content(payload: Any) -> str:
    """Serialize a tool result for the model, capping size to protect its context."""
    content = json.dumps(payload, default=str)
    if len(content) > MAX_TOOL_RESULT_CHARS:
        omitted = len(content) - MAX_TOOL_RESULT_CHARS
        content = (
            content[:MAX_TOOL_RESULT_CHARS]
            + f"... [truncated by eval harness: {omitted} chars omitted]"
        )
    return content


def _is_nonterminal_poll(tool: str, payload: Any) -> bool:
    return (
        tool == "vo_tap_status"
        and isinstance(payload, dict)
        and str(payload.get("phase", "")).upper() in _NONTERMINAL_PHASES
    )


def _assistant_content(blocks) -> list[dict[str, Any]]:
    """Reconstruct assistant content as plain dicts for the next request."""
    content: list[dict[str, Any]] = []
    for b in blocks:
        if b.type == "text":
            content.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
    return content


async def run_task(task: dict[str, Any], cfg: ModelConfig, condition: str) -> TaskRun:
    """Run one task end-to-end under the given context condition."""
    run = TaskRun(
        task_id=task["id"],
        tier=task["tier"],
        condition=condition,
        model=cfg.label,
    )
    ctx = ablated_context if condition == "ablated" else full_context
    started = time.monotonic()
    try:
        with ctx():
            mcp = build_mcp()
            async with Client(mcp) as mcp_client, cfg.client() as model:
                tools = _anthropic_tools(await mcp_client.list_tools())
                messages: list[dict[str, Any]] = [{"role": "user", "content": task["prompt"]}]
                for step in range(MAX_STEPS):
                    run.steps = step + 1
                    resp = await model.messages.create(
                        model=cfg.model,
                        max_tokens=cfg.max_tokens,
                        system=SYSTEM_PROMPT,
                        messages=messages,
                        tools=tools,
                    )
                    if resp.usage:
                        run.input_tokens += resp.usage.input_tokens
                        run.output_tokens += resp.usage.output_tokens
                    messages.append(
                        {"role": "assistant", "content": _assistant_content(resp.content)}
                    )
                    tool_uses = [b for b in resp.content if b.type == "tool_use"]
                    if not tool_uses:
                        run.final_answer = "".join(
                            b.text for b in resp.content if b.type == "text"
                        ).strip()
                        break
                    tool_results = []
                    should_pace = False
                    for tu in tool_uses:
                        result = await mcp_client.call_tool(tu.name, tu.input, raise_on_error=False)
                        payload, is_error = _result_payload(result)
                        run.trace.append(ToolCall(tu.name, dict(tu.input), payload, is_error))
                        should_pace = should_pace or _is_nonterminal_poll(tu.name, payload)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tu.id,
                                "content": _tool_result_content(payload),
                                "is_error": is_error,
                            }
                        )
                    messages.append({"role": "user", "content": tool_results})
                    # Let a still-running async job make progress before the next poll.
                    if should_pace:
                        await asyncio.sleep(ASYNC_POLL_SLEEP_S)
                else:
                    # Distinguish "model got stuck" from "an upstream async job never
                    # finished in our polling budget" — the latter is an environment
                    # latency outcome, not a model/server failure.
                    last = run.trace[-1] if run.trace else None
                    if last and _is_nonterminal_poll(last.tool, last.result):
                        run.async_incomplete = True
                        run.error = (
                            f"async job still {last.result.get('phase')} after "
                            f"{MAX_STEPS} steps (upstream latency, not a model failure)"
                        )
                    else:
                        run.error = f"hit MAX_STEPS ({MAX_STEPS}) without a final answer"
    except Exception as exc:  # harness-level failure; keep going with other tasks
        run.error = f"{type(exc).__name__}: {exc}"
    finally:
        run.latency_s = time.monotonic() - started
    return run
