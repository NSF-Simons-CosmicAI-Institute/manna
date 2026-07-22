"""Structural invariants every shipped skill must satisfy."""

import pytest

from tests.skills._helpers import parse_skill, skill_dirs

# Spec target is ~150 lines; 200 is the hard stop before a skill turns into a manual.
MAX_SKILL_LINES = 200


@pytest.mark.parametrize("skill", skill_dirs(), ids=lambda p: p.name)
def test_frontmatter_valid(skill):
    front, body = parse_skill(skill)
    assert front["name"] == skill.name, "frontmatter name must match the folder name"
    desc = front.get("description", "")
    assert len(desc) >= 60, "description must say concretely when to use the skill"
    assert desc.lower().startswith("use "), "description must lead with the trigger"
    assert body.strip(), "skill body must not be empty"


@pytest.mark.parametrize("skill", skill_dirs(), ids=lambda p: p.name)
def test_skill_is_bounded(skill):
    lines = (skill / "SKILL.md").read_text().splitlines()
    assert len(lines) <= MAX_SKILL_LINES, f"{skill.name} has grown past {MAX_SKILL_LINES} lines"
