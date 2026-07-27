"""Offline self-test for the eval machinery — no model, no external network.

Exercises the parts that don't need the LLM:
  * score.py programmatic checks (arg-check ops, match any/all, ground truth,
    sequence, leak detection)
  * context.py ablation, verified through the REAL in-memory tool path
    (vo_archive_list / vo_schema_describe read local KBs, so no network)

Run:  uv run python -m evals.selftest
"""

from __future__ import annotations

import asyncio

from fastmcp import Client

from evals.context import ablated_context
from evals.harness import TaskRun, ToolCall
from evals.score import score_programmatic
from manna.app import build_mcp


def _run(task_id: str, tier: int, trace: list[ToolCall], answer: str = "") -> TaskRun:
    r = TaskRun(task_id=task_id, tier=tier, condition="full", model="test")
    r.trace = trace
    r.final_answer = answer
    return r


def test_arg_checks_and_tools() -> None:
    task = {
        "id": "x",
        "tier": 3,
        "expect_tools": ["vo_tap_query"],
        "arg_checks": {
            "vo_tap_query": [
                {"arg": "mode", "op": "iequals", "value": "async", "match": "all"},
                {"arg": "adql", "op": "not_contains", "value": "CONTAINS(", "match": "all"},
            ]
        },
    }
    good = _run(
        "x",
        3,
        [
            ToolCall(
                "vo_tap_query", {"mode": "async", "adql": "SELECT 1"}, {"row_count": 1}, False
            ),
            ToolCall(
                "vo_tap_query", {"mode": "ASYNC", "adql": "SELECT 2"}, {"row_count": 1}, False
            ),
        ],
    )
    s = score_programmatic(task, good)
    assert s.checks["expect_tools"] is True
    assert s.checks["args:vo_tap_query"] is True
    assert s.passed is True

    # One sync call -> match:all should fail.
    bad = _run(
        "x",
        3,
        [
            ToolCall("vo_tap_query", {"mode": "async", "adql": "SELECT 1"}, {}, False),
            ToolCall("vo_tap_query", {"mode": "sync", "adql": "CONTAINS(x)"}, {}, False),
        ],
    )
    s = score_programmatic(task, bad)
    assert s.checks["args:vo_tap_query"] is False
    assert s.passed is False


def test_ground_truth_and_sequence() -> None:
    task = {
        "id": "c",
        "tier": 2,
        "expect_tools": ["vo_target_resolve", "vo_cone_search"],
        "sequence": True,
        "ground_truth": {"type": "coords", "ra": 187.706, "dec": 12.391, "tol_deg": 0.01},
    }
    trace = [
        ToolCall("vo_target_resolve", {"name": "M87"}, {"ra": 187.70593, "dec": 12.39112}, False),
        ToolCall("vo_cone_search", {"ra": 187.706, "dec": 12.391, "radius_deg": 0.05}, {}, False),
    ]
    good = _run("c", 2, trace, answer="M87 is at RA 187.7059, Dec +12.3911 degrees.")
    s = score_programmatic(task, good)
    assert s.checks["tool_order"] is True
    assert s.checks["ground_truth"] is True
    assert s.passed is True

    # Wrong order fails the sequence check.
    rev = _run("c", 2, list(reversed(trace)), answer="RA 187.7059 Dec 12.3911")
    assert score_programmatic(task, rev).checks["tool_order"] is False

    # Wrong coords fail ground truth.
    off = _run("c", 2, trace, answer="It is at RA 10.0, Dec 20.0.")
    assert score_programmatic(task, off).checks["ground_truth"] is False


def test_leak_detection() -> None:
    task = {"id": "leak", "tier": 4, "expect_tools": ["vo_tap_query"]}
    leaky = _run(
        "leak",
        4,
        [
            ToolCall(
                "vo_tap_query",
                {"mode": "sync"},
                {"message": "Traceback (most recent call last): boom"},
                True,
            ),
        ],
    )
    s = score_programmatic(task, leaky)
    assert s.checks["no_leak"] is False
    clean = _run(
        "leak",
        4,
        [
            ToolCall(
                "vo_tap_query",
                {"mode": "sync"},
                {"error_class": "archive_error", "message": "sync endpoint returned 500"},
                True,
            ),
        ],
    )
    assert score_programmatic(task, clean).checks["no_leak"] is True


async def test_ablation_through_real_tools() -> None:
    """The ablation must actually change what the tools return."""
    mcp = build_mcp()
    async with Client(mcp) as client:
        full_list = await client.call_tool("vo_archive_list", {"short_name": "nrao"})
        full_schema = await client.call_tool(
            "vo_schema_describe", {"archive": "nrao", "table": "tap_schema.obscore"}
        )
        nrao_full = full_list.structured_content["archives"][0]
        assert len(nrao_full["usage_notes"]) > 0, "baseline NRAO should have usage_notes"
        assert full_schema.structured_content["known"] is True, "baseline obscore known"

        with ablated_context():
            ab_list = await client.call_tool("vo_archive_list", {"short_name": "nrao"})
            ab_schema = await client.call_tool(
                "vo_schema_describe", {"archive": "nrao", "table": "tap_schema.obscore"}
            )
        nrao_ab = ab_list.structured_content["archives"][0]
        assert nrao_ab["usage_notes"] == [], "ablated NRAO must lose usage_notes"
        assert ab_schema.structured_content["known"] is False, "ablated obscore must miss"

        # Context restored after the block.
        after = await client.call_tool("vo_archive_list", {"short_name": "nrao"})
        assert len(after.structured_content["archives"][0]["usage_notes"]) > 0, "must restore"


def main() -> int:
    test_arg_checks_and_tools()
    test_ground_truth_and_sequence()
    test_leak_detection()
    asyncio.run(test_ablation_through_real_tools())
    print("evals selftest: ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
