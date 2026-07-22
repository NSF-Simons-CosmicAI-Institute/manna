---
name: vo-data-discovery
description: Use when starting any astronomy data task — "find data on X", "what
  observations exist of Y", querying an archive, cross-matching a target, or locating
  images or catalogs. Orchestrates the vo_* MCP tools into a reliable discovery workflow.
---

# VO Data Discovery

Workflow discipline for finding astronomical data through the astro-archives MCP
tools. Facts about specific archives (quirks, dialects, table names) are NEVER in
this skill — the server provides them at runtime. Read them; don't guess.

## The chain

Work through these stages in order; skip a stage only when its output is already known.

1. **Resolve the target.** `vo_target_resolve` turns names ("M87") into ICRS decimal
   degrees. Never answer coordinates from memory.
2. **Survey your archives.** `vo_archive_list` lists curated archives with
   `usage_notes`. Read the notes for an archive BEFORE querying it — they carry
   dialect quirks, async requirements, and known traps.
3. **Verify the schema.** `vo_schema_describe` for the table you intend to query.
   Confirm the table and every column exist. Never invent column names.
4. **Query with the right tool:**
   - `vo_tap_query` — catalogs, measurements, counts, anything ADQL.
   - `vo_cone_search` — positional source lists around a point.
   - `vo_sia_search` — images covering a position.
   - `vo_find_observations` — one-shot shortcut: object name OR coords in,
     image/catalog observations out (auto-resolves names). Good first probe.

Quick-look requests can start at step 4 with `vo_find_observations`; go back through
steps 1–3 the moment you need a specific catalog, table, or count.

## Beyond the curated set

The curated list is additive, never gating. If an archive or service is not listed:

- `vo_registry_search` finds IVOA services by keyword, waveband, or capability.
- `vo_registry_describe` inspects one service record in detail.

Then query it with the same tools, passing its endpoint explicitly. Absence from
`vo_archive_list` means "no curated notes", not "unreachable".

## Discipline for larger tasks

- **Probe first.** Before an expensive query, run a `SELECT TOP 5` probe to validate
  table, columns, and geometry. Then scale up.
- **Check `truncated`.** Every inline result carries a top-level `truncated` boolean.
  If true, what you have is NOT the full answer — narrow the search (smaller radius,
  fewer columns, tighter WHERE) or switch to an async TAP query.
- **Branch on `error_class`.** Tool errors return `error_class` + `retry_strategy`.
  Follow the `retry_strategy`; don't blindly re-issue the same call.
- About to write nontrivial ADQL → use the `vo-adql` skill first.
- A query returned a job (async) or a result is large/truncated → use the
  `vo-async-results` skill.

## Reporting

- Coordinates in ICRS decimal degrees; counts as explicit integers.
- Say which archive/service each fact came from.
- If a result was truncated or a job is still running, say so plainly.
