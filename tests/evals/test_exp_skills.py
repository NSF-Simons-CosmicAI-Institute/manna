"""Offline checks for the skills A/B experiment module (no model, no network)."""

from pathlib import Path

import pytest

pytest.importorskip("yaml", reason="eval dependency group not installed")

from evals.exp_skills import SKILLS_DIR, TASK_IDS, load_prompts, write_cwd


def test_task_ids_resolve():
    prompts = load_prompts()
    assert [t["id"] for t in prompts] == TASK_IDS


def test_write_cwd_seeds_skills():
    seeded_dir = Path(write_cwd(with_skills=True)) / ".claude" / "skills"
    seeded = sorted(p.name for p in seeded_dir.iterdir())
    assert seeded == sorted(p.name for p in SKILLS_DIR.glob("vo-*"))
    assert "README.md" not in seeded


def test_write_cwd_baseline_is_empty():
    d = Path(write_cwd(with_skills=False))
    assert not (d / ".claude").exists()
