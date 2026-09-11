"""Glue shared by the eval CLIs: judge config, results writing, tiny math."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from evals.harness import ModelConfig
from manna.tools import TOOL_NAMES

RESULTS_DIR = Path(__file__).with_name("results")

# Tool names before the 0.9.0 rename (dropped the vo_ prefix for descriptive
# names). Saved results files under results/ still carry these in their traces,
# so anything that classifies a trace entry as a MANNA call accepts both.
LEGACY_TOOL_NAMES: dict[str, str] = {
    "vo_archive_list": "list_archives",
    "vo_schema_describe": "describe_table",
    "vo_inspect_table": "preview_table",
    "vo_target_resolve": "resolve_target_name",
    "vo_tap_query": "run_adql_query",
    "vo_tap_status": "get_async_job_status",
    "vo_tap_results": "get_async_job_results",
    "vo_tap_abort": "abort_async_job",
    "vo_registry_search": "search_ivoa_registry",
    "vo_registry_describe": "describe_ivoa_service",
    "vo_cone_search": "search_catalog_by_position",
    "vo_sia_search": "search_images_by_position",
    "vo_find_observations": "find_observations_of_target",
    "vo_count_observations": "count_observations_near_target",
    "vo_survey_target": "survey_archives_for_target",
}


def is_manna_tool(name: object) -> bool:
    """True for a MANNA tool name, current or pre-0.9.0."""
    return name in TOOL_NAMES or name in LEGACY_TOOL_NAMES


def judge_from_env() -> ModelConfig | None:
    """The rubric judge, or None when no EVAL_JUDGE_* config is present."""
    if not (os.getenv("EVAL_JUDGE_NAME") or os.getenv("EVAL_JUDGE_BASE_URL")):
        return None
    return ModelConfig.from_env(prefix="EVAL_JUDGE")


def write_results(record: Any, *, prefix: str, results_dir: Path | None = None) -> Path:
    """Write a timestamped results JSON; returns the path."""
    d = results_dir or RESULTS_DIR
    d.mkdir(exist_ok=True)
    out = d / f"{prefix}-{time.strftime('%Y%m%dT%H%M%S')}.json"
    out.write_text(json.dumps(record, indent=2, default=str))
    return out


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0
