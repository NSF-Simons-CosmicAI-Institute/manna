"""Weighted scorecard across the Pillar-2 matrix — turn raw metrics into a grade.

Reads one or more saved results files (from mcp_quality.py or persona_run.py) and produces
a per-`(model × harness)` scorecard on two axes:

  * WORKFLOW success  — did it reach the right answer?     (accuracy, completion)
  * MCP COMPATIBILITY — how well it works *with the server* (tool-use, clean calls, efficiency)

Each dimension is normalized to 0–1 (higher is better); the composite is a transparent,
tunable weighted mean. Accuracy is read from the file's stored (judge/ground-truth) score;
everything else is recomputed from the runs (no model calls), so the scorecard is cheap and
you can compare arms/personas/models side by side:

    uv run python -m evals.scorecard evals/results/mcp-quality-*.json evals/results/persona-*.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Dimension weights (tunable). Composite = WORKFLOW_W*workflow + COMPAT_W*compatibility.
WORKFLOW_W, COMPAT_W = 0.5, 0.5


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _dimensions(runs: list[dict[str, Any]], accuracy: float | None) -> dict[str, float]:
    n = len(runs) or 1
    tool_use = (
        sum(any(str(c["tool"]).startswith("vo_") for c in r.get("trace", [])) for r in runs) / n
    )
    completion = (
        sum(bool((r.get("final_answer") or "").strip()) and not r.get("error") for r in runs) / n
    )
    total_calls = sum(len(r.get("trace", [])) for r in runs)
    err_calls = sum(1 for r in runs for c in r.get("trace", []) if c.get("is_error"))
    clean = 1.0 - (err_calls / total_calls) if total_calls else 1.0
    mean_calls = _mean([len(r.get("trace", [])) for r in runs])
    efficiency = 1.0 / (1.0 + max(0.0, mean_calls - 1.0))  # 1 call -> 1.0, more -> lower
    acc = accuracy if accuracy is not None else 0.0
    workflow = _mean([acc, completion])
    compatibility = _mean([tool_use, clean, efficiency])
    return {
        "accuracy": round(acc, 3),
        "completion": round(completion, 3),
        "tool_use": round(tool_use, 3),
        "clean_calls": round(clean, 3),
        "efficiency": round(efficiency, 3),
        "WORKFLOW": round(workflow, 3),
        "COMPAT": round(compatibility, 3),
        "COMPOSITE": round(WORKFLOW_W * workflow + COMPAT_W * compatibility, 3),
    }


def _entries(data: dict[str, Any]) -> list[tuple[str, float | None, list[dict[str, Any]]]]:
    """(label, stored-accuracy, runs) per (model x harness) cell in a results file."""
    runs = data.get("runs", [])
    if "per_arm" in data:  # mcp_quality: one entry per arm (custom loop, tool-provider axis)
        model = data.get("model", "?")
        out = []
        for arm, m in data["per_arm"].items():
            arm_runs = [r for r in runs if r.get("arm") == arm]
            out.append((f"{arm}·{model}", m.get("accuracy_rate"), arm_runs))
        return out
    if "persona" in data:  # persona_run: one entry (a real harness)
        s = data.get("summary", {})
        return [(data["persona"], s.get("accuracy_rate"), runs)]
    return [(data.get("model", "?"), None, runs)]


_COLS = [
    "accuracy",
    "completion",
    "tool_use",
    "clean_calls",
    "efficiency",
    "WORKFLOW",
    "COMPAT",
    "COMPOSITE",
]


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print("usage: python -m evals.scorecard <results.json> [<results2.json> ...]")
        return 2
    rows: list[tuple[str, dict[str, float]]] = []
    task_sets: dict[str, frozenset[str]] = {}
    for p in paths:
        data = json.loads(p.read_text())
        for label, acc, runs in _entries(data):
            rows.append((label, _dimensions(runs, acc)))
            task_sets[label] = frozenset(r.get("task_id", "?") for r in runs)

    print(
        "MCP-quality scorecard  (0–1, higher is better; COMPOSITE = "
        f"{WORKFLOW_W}*workflow + {COMPAT_W}*compatibility)\n"
    )
    w = max((len(lbl) for lbl, _ in rows), default=12) + 1
    print(" " * w + "".join(f"{c[:9]:>11s}" for c in _COLS))
    for label, dims in sorted(rows, key=lambda r: -r[1]["COMPOSITE"]):
        print(f"{label:<{w}s}" + "".join(f"{dims[c]:>11.3f}" for c in _COLS))

    # Comparability guard: composites only mean the same thing across the same task set.
    distinct = set(task_sets.values())
    if len(distinct) > 1:
        print(
            "\n⚠ rows were scored on DIFFERENT task sets — composites are not directly "
            "comparable. Task counts per row:"
        )
        for label, ids in task_sets.items():
            print(f"    {label}: {len(ids)} tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
