"""Shared eval glue: judge config resolution + results writing."""

import json

from evals import _common


def test_judge_from_env_none_when_unset(monkeypatch):
    monkeypatch.delenv("EVAL_JUDGE_NAME", raising=False)
    monkeypatch.delenv("EVAL_JUDGE_BASE_URL", raising=False)
    assert _common.judge_from_env() is None


def test_judge_from_env_reads_prefix(monkeypatch):
    monkeypatch.setenv("EVAL_JUDGE_NAME", "claude-haiku-4-5")
    cfg = _common.judge_from_env()
    assert cfg is not None and cfg.model == "claude-haiku-4-5"


def test_write_results(tmp_path):
    out = _common.write_results({"hello": 1}, prefix="unit", results_dir=tmp_path)
    assert out.exists() and out.name.startswith("unit-")
    assert json.loads(out.read_text()) == {"hello": 1}


def test_mean():
    assert _common.mean([1.0, 3.0]) == 2.0
    assert _common.mean([]) == 0.0
