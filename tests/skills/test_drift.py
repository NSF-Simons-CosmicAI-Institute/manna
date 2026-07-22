"""Drift contracts between skills/ and the server.

1. Every vo_* tool a skill mentions exists on the server (catches tool renames).
2. Every vo-<name> cross-reference resolves to a shipped skill folder.
3. Skills stay archive-agnostic: no curated short_name appears anywhere in a skill.
   Archive facts belong in archives/<short_name>.py, surfaced by vo_archive_list /
   vo_schema_describe — see docs/superpowers spec 2026-07-22-mcp-workflow-skills.
"""

import asyncio
import re

import pytest

from astro_archives_mcp.app import build_mcp
from astro_archives_mcp.archives import discover_archives
from tests.skills._helpers import parse_skill, skill_dirs

_TOOL_RE = re.compile(r"\bvo_[a-z_]+\b")
_SKILL_REF_RE = re.compile(r"\bvo-[a-z][a-z-]*\b")


def _full_text(skill) -> str:
    front, body = parse_skill(skill)
    return front.get("description", "") + "\n" + body


@pytest.fixture(scope="module")
def server_tools() -> set[str]:
    tools = asyncio.run(build_mcp().list_tools())
    return {t.name for t in tools}


@pytest.mark.parametrize("skill", skill_dirs(), ids=lambda p: p.name)
def test_mentioned_tools_exist(skill, server_tools):
    mentioned = set(_TOOL_RE.findall(_full_text(skill)))
    assert mentioned, f"{skill.name} mentions no vo_* tools at all"
    unknown = mentioned - server_tools
    assert not unknown, f"{skill.name} references tools the server does not ship: {sorted(unknown)}"


@pytest.mark.parametrize("skill", skill_dirs(), ids=lambda p: p.name)
def test_cross_references_resolve(skill):
    shipped = {p.name for p in skill_dirs()}
    refs = set(_SKILL_REF_RE.findall(_full_text(skill)))
    assert refs <= shipped, f"{skill.name} references unknown skills: {sorted(refs - shipped)}"


@pytest.mark.parametrize("skill", skill_dirs(), ids=lambda p: p.name)
def test_archive_agnostic(skill):
    text = _full_text(skill).lower()
    offenders = [
        a.short_name
        for a in discover_archives()
        if re.search(rf"\b{re.escape(a.short_name.lower())}\b", text)
    ]
    assert not offenders, (
        f"{skill.name} names curated archives {offenders}; skills must stay "
        "archive-agnostic — archive facts belong in archives/<short_name>.py"
    )
