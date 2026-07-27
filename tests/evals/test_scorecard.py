"""Offline unit tests for the weighted scorecard (evals/scorecard.py)."""

from __future__ import annotations

from evals.scorecard import _dimensions, _entries, _mean


def _run(*, tools=(), answer="ok", error=None):
    return {
        "trace": [{"tool": t, "is_error": e} for t, e in tools],
        "final_answer": answer,
        "error": error,
    }


def test_mean_empty_is_zero():
    assert _mean([]) == 0.0
    assert _mean([1.0, 3.0]) == 2.0


def test_dimensions_perfect_single_call():
    runs = [_run(tools=[("vo_target_resolve", False)])]
    d = _dimensions(runs, accuracy=1.0)
    assert d["accuracy"] == 1.0
    assert d["completion"] == 1.0
    assert d["tool_use"] == 1.0
    assert d["clean_calls"] == 1.0
    assert d["efficiency"] == 1.0  # exactly one call → 1.0
    assert d["COMPOSITE"] == 1.0


def test_tool_use_zero_when_no_vo_calls():
    # a strong model answering from memory (no MCP tool calls)
    runs = [_run(tools=[], answer="M87 is at ...")]
    d = _dimensions(runs, accuracy=1.0)
    assert d["tool_use"] == 0.0
    assert d["completion"] == 1.0
    # workflow perfect, compat dragged down by zero tool-use
    assert d["WORKFLOW"] == 1.0
    assert d["COMPAT"] < 1.0


def test_clean_calls_penalizes_tool_errors():
    runs = [_run(tools=[("vo_tap_query", True), ("vo_tap_query", False)])]
    d = _dimensions(runs, accuracy=0.0)
    assert d["clean_calls"] == 0.5  # 1 of 2 calls errored


def test_efficiency_decreases_with_more_calls():
    one = _dimensions([_run(tools=[("vo_x", False)])], 1.0)["efficiency"]
    many = _dimensions([_run(tools=[("vo_x", False)] * 5)], 1.0)["efficiency"]
    assert one == 1.0
    assert 0.0 < many < one


def test_completion_false_on_error_or_empty_answer():
    assert _dimensions([_run(answer="", error=None)], 1.0)["completion"] == 0.0
    assert _dimensions([_run(answer="x", error="boom")], 1.0)["completion"] == 0.0


def test_accuracy_none_treated_as_zero():
    d = _dimensions([_run(tools=[("vo_x", False)])], accuracy=None)
    assert d["accuracy"] == 0.0


# --------------------------------------------------------------------------- #
# _entries — file-shape detection (mcp_quality per_arm vs persona vs generic)
# --------------------------------------------------------------------------- #
def test_entries_mcp_quality_splits_by_arm():
    data = {
        "model": "qwen3.5",
        "per_arm": {"mcp": {"accuracy_rate": 0.9}, "raw_tap": {"accuracy_rate": 0.3}},
        "runs": [
            {"arm": "mcp", "trace": [], "task_id": "a"},
            {"arm": "raw_tap", "trace": [], "task_id": "a"},
        ],
    }
    entries = _entries(data)
    labels = {lbl for lbl, _, _ in entries}
    assert labels == {"mcp·qwen3.5", "raw_tap·qwen3.5"}
    by_label = {lbl: (acc, runs) for lbl, acc, runs in entries}
    assert by_label["mcp·qwen3.5"][0] == 0.9
    assert len(by_label["mcp·qwen3.5"][1]) == 1  # only the mcp run


def test_entries_persona_single_cell():
    data = {"persona": "claude-code", "summary": {"accuracy_rate": 1.0}, "runs": [{"trace": []}]}
    entries = _entries(data)
    assert len(entries) == 1
    label, acc, runs = entries[0]
    assert label == "claude-code"
    assert acc == 1.0
