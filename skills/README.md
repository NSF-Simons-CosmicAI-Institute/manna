# Workflow skills for astro-archives-mcp

Claude Code [Agent Skills](https://docs.anthropic.com/en/docs/claude-code) that teach
an agent how to orchestrate this server's `vo_*` tools for larger research workflows.
The skills are **archive-agnostic by rule**: facts about specific archives (dialect
quirks, table names, async requirements) live server-side in
`src/astro_archives_mcp/archives/<short_name>.py` and reach the model at runtime via
`vo_archive_list` / `vo_schema_describe`. Skills teach the *workflow*; the server
supplies the *facts*. `tests/skills/` enforces this mechanically.

| Skill | Use when |
|---|---|
| `vo-data-discovery` | Starting any "find/get data on X" task — the entry point |
| `vo-async-results`  | A TAP query went async / a result is too large for inline |
| `vo-adql`           | Composing or debugging ADQL for `vo_tap_query` |

## Install

**Claude Code (personal):** symlink the skill folders (not this README) into your
skills directory, then `git pull` keeps them fresh:

    ln -s "$(pwd)"/skills/vo-* ~/.claude/skills/

**Claude Code (per-project):** same, into the project's `.claude/skills/`.

**CosmicCoder / JupyterHub:** baked into the persona image — see the skills COPY
step in `deploy/frontend/frontend.Dockerfile`. Nothing to do at runtime.

## Rules for editing

- Never name a curated archive or embed table-specific facts (test-enforced).
- Keep each SKILL.md under ~150 lines, imperative voice, checklists over prose.
- A tool rename or workflow change and its skill update land in the same PR —
  `tests/skills/test_drift.py` fails on references to tools the server no longer ships.
- A deployment that doesn't want a skill deletes its folder (same fork-and-trim
  philosophy as `archives/`).
