"""Contract: the server is agent-agnostic.

src/astro_archives_mcp/ must never import agent-side code (evals/, deploy/) or
model-vendor SDKs (anthropic, openai). This is the load-bearing invariant behind
the cosmic-coder split: the MCP server has zero knowledge of any agent or model.
Agent->server dependencies are allowed (cosmic-coder pins this repo); the reverse
direction is forbidden forever.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "astro_archives_mcp"
FORBIDDEN = frozenset({"evals", "deploy", "anthropic", "openai"})


def _imported_roots(path: Path) -> set[str]:
    """Top-level package names imported by a Python file (absolute imports only)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_scanner_detects_forbidden_import(tmp_path):
    """The scanner itself must catch a smuggled agent-side import."""
    bad = tmp_path / "bad.py"
    bad.write_text("from evals.harness import TaskRun\nimport anthropic\n")
    assert {"evals", "anthropic"} <= _imported_roots(bad)


def test_src_never_imports_agent_side_code():
    assert SRC.is_dir(), f"src tree not found at {SRC}"
    offenders: dict[str, list[str]] = {}
    for py in sorted(SRC.rglob("*.py")):
        hits = _imported_roots(py) & FORBIDDEN
        if hits:
            offenders[str(py.relative_to(SRC))] = sorted(hits)
    assert not offenders, f"agent-agnostic invariant violated: {offenders}"
