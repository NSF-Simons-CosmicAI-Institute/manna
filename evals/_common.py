"""Glue shared by the eval CLIs: judge config, results writing, tiny math."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from evals.harness import ModelConfig

RESULTS_DIR = Path(__file__).with_name("results")


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
