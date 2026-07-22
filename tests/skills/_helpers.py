"""Discovery + parsing for the skills layer (skills/ at the repo root).

Skills are markdown with a FLAT `key: value` frontmatter block by design — parsed
by hand here so the offline test suite needs no yaml dependency (pyyaml lives in
the eval group only).
"""

from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


def skill_dirs() -> list[Path]:
    """Every shipped skill folder, sorted. Raises if the layer is missing/empty."""
    if not SKILLS_DIR.is_dir():
        raise AssertionError(f"skills/ directory missing at {SKILLS_DIR}")
    dirs = sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir())
    if not dirs:
        raise AssertionError("skills/ exists but contains no skill folders")
    return dirs


def parse_skill(skill_dir: Path) -> tuple[dict[str, str], str]:
    """(frontmatter, body) for a SKILL.md.

    Frontmatter must be a flat `key: value` block delimited by `---` lines;
    indented lines continue the previous value (folded with spaces).
    """
    text = (skill_dir / "SKILL.md").read_text()
    assert text.startswith("---\n"), f"{skill_dir.name}: SKILL.md must start with '---'"
    front_raw, sep, body = text[4:].partition("\n---\n")
    assert sep, f"{skill_dir.name}: unterminated frontmatter block"
    front: dict[str, str] = {}
    key: str | None = None
    for line in front_raw.splitlines():
        if not line.strip():
            continue
        if line[0] in (" ", "\t") and key is not None:
            front[key] += " " + line.strip()
            continue
        k, colon, v = line.partition(":")
        assert colon, f"{skill_dir.name}: bad frontmatter line {line!r}"
        key = k.strip()
        front[key] = v.strip()
    return front, body
