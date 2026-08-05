"""Agent loop: drive a real LLM through the MCP tools and record the trace.

Model calls go to the configured Anthropic-Messages endpoint (the dlai01 vLLM
gpt-oss-120b by default — the same endpoint the Jupyter AI persona uses). Tool calls
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
from typing import Any

from evals.context import ablated_context, full_context
from manna.archives._traps import CHEATSHEET_HEADER

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


# The hand-written _SILENT_TRAP_CHEATSHEET that used to live here is gone: its own
# comment said "a real server-side version would derive this from tagged notes on the
# active archives", and issue #57 did exactly that. The server now ships the blob on
# vo_tap_query's description by default (archives/_traps.py), so the harness no longer
# ADDS anything — the ablation arm SUBTRACTS it instead. Keeping a second copy here
# would silently drift from what the server actually serves.


def strip_cheatsheet(description: str) -> str:
    """`description` with the server-injected trap cheatsheet removed.

    The subtraction lives here, not in the server package: only the ablation arm
    ever wants the blob back OUT of an otherwise identical tool surface.
    `CHEATSHEET_HEADER` is the seam the server exposes for exactly this cut.
    No-op if the blob isn't there.
    """
    head, sep, _ = description.partition(CHEATSHEET_HEADER)
    return head.rstrip() if sep else description


# Tools that surface the server's CURATED archive knowledge. Withholding them
# (no_discovery) forces the quirks to reach the model only via injected tool
# descriptions or the model's own priors — the clean test for experiment (a).
_DISCOVERY_TOOLS = {"vo_archive_list", "vo_schema_describe"}

# Env-driven tool-ablation seam: EVAL_EXCLUDE_TOOLS is a comma-separated list of
# tool names withheld from the agent's tool surface for a with/without value-add
# A/B (e.g. the purpose-built facades vo_count_observations,vo_survey_target,
# vo_inspect_table). Read per call so a single process picks up the current env;
# unset/empty => nothing excluded (default = the full shipped tool set).
_EXCLUDE_TOOLS_ENV = "EVAL_EXCLUDE_TOOLS"


def _excluded_tools() -> set[str]:
    raw = os.getenv(_EXCLUDE_TOOLS_ENV, "")
    return {name.strip() for name in raw.split(",") if name.strip()}


# Markers of a TRANSIENT endpoint failure (shared vLLM connection blip / timeout)
# — distinct from a real model/tool error. Matched on the exception's class name +
# message so we don't depend on a specific SDK's exception classes. A run that hits
# one of these is retried rather than scored as a task failure, which otherwise
# silently biases an ablation arm that happens to run during a flaky window.
_TRANSIENT_MARKERS = (
    "APIConnectionError",
    "APITimeoutError",
    "Connection error",
    "timed out",
    "Timeout",
    "Overloaded",
)


def _is_transient(exc: BaseException) -> bool:
    s = f"{type(exc).__name__}: {exc}"
    return any(m in s for m in _TRANSIENT_MARKERS)


async def _complete_with_retry(
    model, system, convo, tools, *, attempts: int = 3, backoff: float = 2.0
):
    """`model.complete`, retried on transient endpoint errors with linear backoff.

    Non-transient exceptions propagate immediately; the last attempt re-raises so a
    persistent outage still surfaces as the run's error (never silently swallowed).
    """
    for i in range(attempts):
        try:
            return await model.complete(system, convo, tools)
        except Exception as exc:  # noqa: BLE001 — re-raised unless transient + attempts left
            if i == attempts - 1 or not _is_transient(exc):
                raise
            await asyncio.sleep(backoff * (i + 1))


def _anthropic_tools(
    mcp_tools, inject_notes: bool = True, no_discovery: bool = False
) -> list[dict[str, Any]]:
    """Convert FastMCP tool descriptors to Anthropic tool-use format.

    - ``inject_notes``: keep the server's silent-trap cheatsheet on vo_tap_query's
      description. Defaults True because that is now production behaviour; passing
      False STRIPS it, which is how experiment (a) isolates the injection's value.
    - ``no_discovery``: withhold the curated-knowledge tools (vo_archive_list,
      vo_schema_describe) so the model can't consult them.
    - ``EVAL_EXCLUDE_TOOLS`` (env): additionally withhold any named tools — the
      seam for the purpose-built-tools value-add A/B (with vs without).
    """
    excluded = _excluded_tools()
    out = []
    for t in mcp_tools:
        if no_discovery and t.name in _DISCOVERY_TOOLS:
            continue
        if t.name in excluded:
            continue
        desc = t.description or ""
        if not inject_notes and t.name == "vo_tap_query":
            desc = strip_cheatsheet(desc)
        out.append(
            {
                "name": t.name,
                "description": desc,
                "input_schema": t.inputSchema or {"type": "object", "properties": {}},
            }
        )
    return out


def _result_payload(result) -> tuple[Any, bool]:
    """Extract a JSON-able payload + error flag from a FastMCP call result.

    The server returns tool errors as ordinary payloads discriminated by
    `error_class` (never MCP isError — see tools/_constants.py), so the flag
    alone undercounts: treat an error_class-carrying payload as an error call.
    """
    is_error = bool(getattr(result, "is_error", False))
    payload = getattr(result, "structured_content", None)
    if payload is None:
        # Fall back to concatenated text content blocks.
        blocks = getattr(result, "content", None) or []
        texts = [getattr(b, "text", "") for b in blocks]
        payload = {"text": "".join(texts)}
    if isinstance(payload, dict) and "error_class" in payload:
        is_error = True
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
    inject_notes: bool = True,
    no_discovery: bool = False,
    arm: str = "mcp",
) -> TaskRun:
    """Run one task end-to-end under the given context condition and tool arm.

    `arm` selects the tool provider: 'mcp' (full server), 'raw_tap', or 'raw_web'
    (the MCP-quality no-curation baselines). inject_notes/no_discovery apply to 'mcp'.
    inject_notes defaults True to mirror production; False strips the server's
    silent-trap cheatsheet back off.
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
                    comp = await _complete_with_retry(model, SYSTEM_PROMPT, convo, tools)
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
