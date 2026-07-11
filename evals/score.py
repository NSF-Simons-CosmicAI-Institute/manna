"""Score a TaskRun against its tasks.yaml spec.

Two kinds of checks:
  * programmatic — expect/forbid tools, call order, arg constraints, ground-truth
    on the final answer, and a safety scan (no tokens/tracebacks/paths leaked).
  * LLM-judge — for open-ended `rubric` tasks, graded by a *separate* judge model
    (hosted Claude), never the model under test grading itself.

A task passes iff every applicable check passes. Checks that can't run (e.g. a
rubric with no judge configured) are recorded as None and excluded from pass/fail,
but surfaced so a run isn't silently reported as "all green" when it wasn't.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from evals.harness import ModelConfig, TaskRun

TASKS_PATH = Path(__file__).with_name("tasks.yaml")

# Substrings that must never appear in anything the model saw (redaction invariant).
_LEAK_PATTERNS = (
    "Traceback (most recent call last)",
    "Bearer ",
    "/Users/",
    "/build/src",
    "site-packages/",
    'File "',
)


def load_tasks(path: Path | None = None, tier: int | None = None) -> list[dict[str, Any]]:
    tasks = yaml.safe_load((path or TASKS_PATH).read_text())
    if tier is not None:
        tasks = [t for t in tasks if t.get("tier") == tier]
    return tasks


@dataclass
class TaskScore:
    task_id: str
    tier: int
    condition: str
    checks: dict[str, bool | None] = field(default_factory=dict)
    judge_reason: str | None = None
    judge_quality: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        vals = [v for v in self.checks.values() if v is not None]
        return bool(vals) and all(vals)

    @property
    def has_unscored(self) -> bool:
        return any(v is None for v in self.checks.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "tier": self.tier,
            "condition": self.condition,
            "passed": self.passed,
            "checks": self.checks,
            "judge_quality": self.judge_quality,
            "judge_reason": self.judge_reason,
            "notes": self.notes,
        }


# --------------------------------------------------------------------------- #
# arg-check primitives
# --------------------------------------------------------------------------- #
def _dotted(d: Any, path: str) -> Any:
    cur = d
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur


def _apply_op(value: Any, check: dict[str, Any]) -> bool:
    op = check["op"]
    if op == "present":
        return value is not None
    if value is None:
        # A missing arg trivially satisfies negative ops, fails positive ones.
        return op in ("not_contains", "not_icontains")

    s = str(value)
    target = check.get("value")

    if op == "contains":
        return str(target) in s
    if op == "not_contains":
        return str(target) not in s
    if op == "icontains":
        return str(target).lower() in s.lower()
    if op == "not_icontains":
        return str(target).lower() not in s.lower()
    if op == "equals":
        return s == str(target)
    if op == "iequals":
        return s.lower() == str(target).lower()
    if op == "regex":
        return re.search(str(target), s) is not None
    if op in ("near", "gte", "lte"):
        try:
            num = float(value)
        except (TypeError, ValueError):
            return False
        if op == "near":
            return abs(num - float(target)) <= float(check.get("tol", 0.0))
        if op == "gte":
            return num >= float(target)
        return num <= float(target)
    raise ValueError(f"unknown arg-check op: {op!r}")


def _check_calls(calls: list[dict[str, Any]], check: dict[str, Any]) -> bool:
    """Apply one arg-check across all calls to a tool per its match policy."""
    if not calls:
        return False
    match = check.get("match", "any")
    results = [_apply_op(_dotted(c["args"], check["arg"]), check) for c in calls]
    return all(results) if match == "all" else any(results)


# --------------------------------------------------------------------------- #
# programmatic scoring
# --------------------------------------------------------------------------- #
def _tools_in_order(trace_tools: list[str], expected: list[str]) -> bool:
    """Do `expected` appear as a subsequence of the actual tool-call order?"""
    it = iter(trace_tools)
    return all(tool in it for tool in expected)


def _ground_truth_ok(gt: dict[str, Any], answer: str) -> bool:
    kind = gt["type"]
    if kind == "coords":
        nums = [float(x) for x in re.findall(r"[-+]?\d+\.\d+", answer)]
        if not nums:
            return False
        tol = float(gt.get("tol_deg", 0.01))
        ra_ok = any(abs(n - float(gt["ra"])) <= tol for n in nums)
        dec_ok = any(abs(n - float(gt["dec"])) <= tol for n in nums)
        return ra_ok and dec_ok
    if kind == "contains":
        low = answer.lower()
        return all(str(v).lower() in low for v in gt["values"])
    if kind == "regex":
        return re.search(gt["pattern"], answer) is not None
    if kind == "nonempty":
        return bool(answer.strip())
    raise ValueError(f"unknown ground_truth type: {kind!r}")


def _leaked(run: TaskRun) -> str | None:
    """Return the first leak pattern found in any tool result, else None."""
    blob = json.dumps([c.result for c in run.trace], default=str)
    for pat in _LEAK_PATTERNS:
        if pat in blob:
            return pat
    return None


def score_programmatic(task: dict[str, Any], run: TaskRun) -> TaskScore:
    score = TaskScore(task_id=task["id"], tier=task["tier"], condition=run.condition)
    trace_tools = [c.tool for c in run.trace]
    calls_by_tool: dict[str, list[dict[str, Any]]] = {}
    for c in run.trace:
        calls_by_tool.setdefault(c.tool, []).append({"args": c.args, "result": c.result})

    if run.error:
        score.notes.append(f"harness error: {run.error}")

    if "expect_tools" in task:
        score.checks["expect_tools"] = all(t in trace_tools for t in task["expect_tools"])
    if "expect_any_of" in task:
        score.checks["expect_any_of"] = any(t in trace_tools for t in task["expect_any_of"])
    if "forbid_tools" in task:
        score.checks["forbid_tools"] = not any(t in trace_tools for t in task["forbid_tools"])
    if task.get("sequence"):
        score.checks["tool_order"] = _tools_in_order(trace_tools, task["expect_tools"])

    for tool, checks in (task.get("arg_checks") or {}).items():
        calls = calls_by_tool.get(tool, [])
        ok = all(_check_calls(calls, chk) for chk in checks)
        score.checks[f"args:{tool}"] = ok

    if "ground_truth" in task:
        score.checks["ground_truth"] = _ground_truth_ok(task["ground_truth"], run.final_answer)

    # Safety invariant, applied to every task (primary criterion for t4-no-leak).
    leak = _leaked(run)
    score.checks["no_leak"] = leak is None
    if leak:
        score.notes.append(f"LEAK: found {leak!r} in a tool result")

    return score


# --------------------------------------------------------------------------- #
# LLM-judge for rubric tasks
# --------------------------------------------------------------------------- #
_JUDGE_SYSTEM = (
    "You are a strict evaluator of an AI astronomy assistant. Given the user's "
    "request, a grading rubric, the assistant's final answer, and its tool-call "
    "trace, decide whether the answer satisfies the rubric.\n"
    "Output ONLY a single-line JSON object and NOTHING else — no reasoning, no "
    "preamble, no markdown, no thinking. The very first character of your reply "
    'must be "{". Schema: {"pass": true|false, "quality": 1-5, "reason": "one sentence"}.'
)


def _extract_verdict(text: str) -> dict | None:
    """Pull the JSON verdict out of a judge reply, tolerating preamble/reasoning.

    Reasoning models (e.g. Qwen3.5) often emit a "Thinking Process:" preamble
    before the JSON. Scan for balanced {...} objects and return the last one that
    parses and carries a "pass" key.
    """
    candidates = re.findall(r"\{[^{}]*\}", text, re.DOTALL)
    # Also try the greedy first-to-last-brace span for nested/multiline objects.
    greedy = re.search(r"\{.*\}", text, re.DOTALL)
    if greedy:
        candidates.append(greedy.group(0))
    for cand in reversed(candidates):
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "pass" in obj:
            return obj
    return None


def _compact_trace(run: TaskRun) -> str:
    return "\n".join(
        f"{i + 1}. {c.tool}({json.dumps(c.args, default=str)})"
        + ("  [ERROR]" if c.is_error else "")
        for i, c in enumerate(run.trace)
    )


async def score_rubric(
    task: dict[str, Any], run: TaskRun, judge: ModelConfig
) -> tuple[bool | None, int | None, str | None]:
    """Grade a rubric task with the judge model. Returns (pass, quality, reason)."""
    prompt = (
        f"USER REQUEST:\n{task['prompt']}\n\n"
        f"RUBRIC:\n{task['rubric']}\n\n"
        f"ASSISTANT FINAL ANSWER:\n{run.final_answer or '(no final answer produced)'}\n\n"
        f"TOOL-CALL TRACE:\n{_compact_trace(run) or '(no tools called)'}"
    )
    from evals.model_backends import make_backend

    try:
        # Route through the model-backend layer so the judge can be Anthropic OR OpenAI.
        async with make_backend(judge) as backend:
            comp = await backend.complete(_JUDGE_SYSTEM, [{"role": "user", "text": prompt}], [])
    except Exception as exc:  # auth/network/rate-limit -> degrade to unscored, don't crash
        return None, None, f"judge call failed: {type(exc).__name__}: {exc}"
    verdict = _extract_verdict(comp.text)
    if verdict is None:
        return None, None, f"judge returned no parseable verdict: {comp.text[:120]!r}"
    return bool(verdict.get("pass")), verdict.get("quality"), verdict.get("reason")


async def score_task(
    task: dict[str, Any], run: TaskRun, judge: ModelConfig | None = None
) -> TaskScore:
    """Full score: programmatic checks + (if rubric present) the LLM judge."""
    score = score_programmatic(task, run)
    if "rubric" in task and task["rubric"]:
        if judge is None:
            score.checks["rubric"] = None
            score.notes.append("rubric not scored (no judge configured)")
        else:
            passed, quality, reason = await score_rubric(task, run, judge)
            score.checks["rubric"] = passed
            score.judge_quality = quality
            score.judge_reason = reason
    return score
