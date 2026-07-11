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

from evals.context import ablated_context, full_context

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

# Rounds of (assistant -> tool calls -> results) before we give up on a task.
# Async TAP lifecycles poll vo_tap_status repeatedly, so this must be generous.
# Defaults; the live values are read from env at run_task() call time (via _max_steps /
# _poll_sleep) so evals/.env — loaded after import — can still override them.
MAX_STEPS = 20
DEFAULT_MAX_TOKENS = 4096

# When a status poll comes back non-terminal, wait before handing control back to
# the model so the upstream job actually has wall-clock time to progress — otherwise
# the model burns its whole step budget on back-to-back polls of a QUEUED job.
ASYNC_POLL_SLEEP_S = 6.0
_NONTERMINAL_PHASES = {"PENDING", "QUEUED", "EXECUTING", "HELD", "SUSPENDED", "UNKNOWN"}


def _max_steps() -> int:
    return int(os.getenv("EVAL_MAX_STEPS", str(MAX_STEPS)))


def _poll_sleep() -> float:
    return float(os.getenv("EVAL_ASYNC_POLL_SLEEP", str(ASYNC_POLL_SLEEP_S)))


# Cap the size of a single tool result fed back to the model. A large
# vo_registry_describe / preview payload can otherwise blow the model's context
# window in one shot. The FULL result is still recorded in the trace for scoring;
# only what the model sees is trimmed (a real client would manage context too).
MAX_TOOL_RESULT_CHARS = 24000

SYSTEM_PROMPT = (
    "You are an assistant for professional astronomers. Use the available tools to "
    "answer the user's request rather than answering from memory. When you report sky "
    "coordinates, give them in decimal degrees (ICRS). When you report a count, state "
    "the integer explicitly. Finish with a concise final answer."
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
    backend: str = "anthropic"  # "anthropic" | "openai" (model-under-test API shape)

    @classmethod
    def from_env(cls, prefix: str = "EVAL_MODEL") -> ModelConfig:
        """Build from env.

        The model-under-test (prefix ``EVAL_MODEL``) inherits the persona's bare
        ``ANTHROPIC_*`` vars, so the same ``deploy/frontend/.env`` that runs the
        persona also runs the eval. Any OTHER prefix (e.g. ``EVAL_JUDGE``) is read
        from its own vars ONLY — no ANTHROPIC_* fallback — so a hosted-Claude judge
        stays fully isolated from a local-proxy model-under-test (different base_url,
        different auth, no leaked Basic-auth header).

        Recognized ({PREFIX} = EVAL_MODEL or EVAL_JUDGE):
          {PREFIX}_NAME[/ ANTHROPIC_DEFAULT_OPUS_MODEL]  -> served model name
          {PREFIX}_BASE_URL[/ ANTHROPIC_BASE_URL]        -> endpoint (omit for hosted)
          {PREFIX}_API_KEY[/ ANTHROPIC_API_KEY]          -> auth token
          {PREFIX}_CUSTOM_HEADERS[/ ANTHROPIC_CUSTOM_HEADERS] -> "Header: v; Header2: v2"
        (the ANTHROPIC_* fallbacks in brackets apply to EVAL_MODEL only.)
        """
        inherit = prefix == "EVAL_MODEL"

        def get(suffix: str, anthropic_var: str | None = None) -> str | None:
            val = os.getenv(f"{prefix}_{suffix}")
            if not val and inherit and anthropic_var:
                val = os.getenv(anthropic_var)
            return val or None

        name = get("NAME", "ANTHROPIC_DEFAULT_OPUS_MODEL") or "claude-opus-4-8"
        base_url = get("BASE_URL", "ANTHROPIC_BASE_URL")
        api_key = get("API_KEY", "ANTHROPIC_API_KEY") or "dummy"
        raw_headers = get("CUSTOM_HEADERS", "ANTHROPIC_CUSTOM_HEADERS") or ""
        return cls(
            model=name,
            base_url=base_url,
            api_key=api_key,
            extra_headers=_parse_custom_headers(raw_headers),
            label=os.getenv(f"{prefix}_LABEL", name),
            backend=os.getenv(f"{prefix}_BACKEND", "anthropic"),
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
    arm: str = "mcp"  # "mcp" | "raw_tap" | "raw_web" (MCP-quality comparison arm)
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
            "arm": self.arm,
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


# Distilled to the behavior-changing bits of the SILENT-failure traps — the ones
# that return wrong data with no error, so the model can't self-correct reactively
# and genuinely needs preventive guidance. Loud traps (LOWER/UPPER, sync 5xx) throw,
# so they belong in the error `hint`, not here — keeping this ~10% the size of the
# raw usage_notes it replaces (a tool description is re-sent every turn). A real
# server-side version would derive this from tagged notes in KNOWN_ARCHIVES.
_SILENT_TRAP_CHEATSHEET = (
    "Archive quirks that FAIL SILENTLY (wrong results, no error) — apply before querying:\n"
    "- Astro Data Lab (datalab.noirlab): ADQL geometry (CONTAINS/CIRCLE/POINT) is NOT "
    "translated (passed to PostgreSQL, errors). For a cone use "
    "q3c_radial_query(ra, dec, <ra0>, <dec0>, <radius_deg>) = 't'; a ra/dec BETWEEN box "
    "also works but returns a box, not a circle.\n"
    "- ALMA (almascience): rows are per spectral-window; count observations with "
    "COUNT(DISTINCT member_ous_uid), not COUNT(*).\n"
    "- NRAO (data-query.nrao): obscore table is tap_schema.obscore (not ivoa.obscore); "
    "data reads need mode='async'."
)


def _archive_notes_blob() -> str:
    """Compact, preventive archive-quirk cheatsheet injected into the vo_tap_query
    description (experiment (a)). Deliberately tiny — see the constant's rationale."""
    return _SILENT_TRAP_CHEATSHEET


# Tools that surface the server's CURATED archive knowledge. Withholding them
# (no_discovery) forces the quirks to reach the model only via injected tool
# descriptions or the model's own priors — the clean test for experiment (a).
_DISCOVERY_TOOLS = {"vo_archive_list", "vo_schema_describe"}


def _anthropic_tools(
    mcp_tools, inject_notes: bool = False, no_discovery: bool = False
) -> list[dict[str, Any]]:
    """Convert FastMCP tool descriptors to Anthropic tool-use format.

    - ``inject_notes``: append the archive-quirk cheatsheet to vo_tap_query's
      description (experiment (a) — context-in-tool-descriptions).
    - ``no_discovery``: withhold the curated-knowledge tools (vo_archive_list,
      vo_schema_describe) so the model can't consult them.
    """
    blob = _archive_notes_blob() if inject_notes else ""
    out = []
    for t in mcp_tools:
        if no_discovery and t.name in _DISCOVERY_TOOLS:
            continue
        desc = t.description or ""
        if inject_notes and t.name == "vo_tap_query":
            desc = f"{desc}\n\n{blob}"
        out.append(
            {
                "name": t.name,
                "description": desc,
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


async def run_task(
    task: dict[str, Any],
    cfg: ModelConfig,
    condition: str,
    inject_notes: bool = False,
    no_discovery: bool = False,
    arm: str = "mcp",
) -> TaskRun:
    """Run one task end-to-end under the given context condition and tool arm.

    `arm` selects the tool provider: 'mcp' (full server), 'raw_tap', or 'raw_web'
    (the MCP-quality no-curation baselines). inject_notes/no_discovery apply to 'mcp'.
    """
    from evals.model_backends import make_backend
    from evals.providers import make_provider

    run = TaskRun(
        task_id=task["id"],
        tier=task["tier"],
        condition=condition,
        model=cfg.label,
        arm=arm,
    )
    # Ablation only affects the curated KB, i.e. the 'mcp' arm; no-op for raw arms.
    ctx = ablated_context if condition == "ablated" else full_context
    started = time.monotonic()
    max_steps, poll_sleep = _max_steps(), _poll_sleep()
    try:
        with ctx():
            provider = make_provider(arm, inject_notes=inject_notes, no_discovery=no_discovery)
            async with provider, make_backend(cfg) as model:
                tools = provider.tools
                # Neutral conversation the backend translates to its own wire format.
                convo: list[dict[str, Any]] = [{"role": "user", "text": task["prompt"]}]
                for step in range(max_steps):
                    run.steps = step + 1
                    comp = await model.complete(SYSTEM_PROMPT, convo, tools)
                    run.input_tokens += comp.input_tokens
                    run.output_tokens += comp.output_tokens
                    convo.append(
                        {"role": "assistant", "text": comp.text, "tool_uses": comp.tool_uses}
                    )
                    if not comp.tool_uses:
                        run.final_answer = comp.text
                        break
                    results = []
                    should_pace = False
                    for tu in comp.tool_uses:
                        payload, is_error = await provider.call(tu["name"], dict(tu["input"]))
                        run.trace.append(ToolCall(tu["name"], dict(tu["input"]), payload, is_error))
                        should_pace = should_pace or _is_nonterminal_poll(tu["name"], payload)
                        results.append(
                            {
                                "tool_use_id": tu["id"],
                                "content": _tool_result_content(payload),
                                "is_error": is_error,
                            }
                        )
                    convo.append({"role": "tool", "results": results})
                    # Let a still-running async job make progress before the next poll.
                    if should_pace:
                        await asyncio.sleep(poll_sleep)
                else:
                    # Distinguish "model got stuck" from "an upstream async job never
                    # finished in our polling budget" — the latter is an environment
                    # latency outcome, not a model/server failure.
                    last = run.trace[-1] if run.trace else None
                    if last and _is_nonterminal_poll(last.tool, last.result):
                        run.async_incomplete = True
                        run.error = (
                            f"async job still {last.result.get('phase')} after "
                            f"{max_steps} steps (upstream latency, not a model failure)"
                        )
                    else:
                        run.error = f"hit max steps ({max_steps}) without a final answer"
    except Exception as exc:  # harness-level failure; keep going with other tasks
        run.error = f"{type(exc).__name__}: {exc}"
    finally:
        run.latency_s = time.monotonic() - started
    return run
