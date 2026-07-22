---
name: vo-adql
description: Use before composing or debugging any ADQL for vo_tap_query — building
  SELECT statements, positional or geometry queries, counts, joins, or when a TAP
  query errors or returns something unexpected.
---

# Writing ADQL That Works

Rules for composing ADQL against ANY archive through `vo_tap_query`. Dialect quirks
are archive-specific and live server-side: `vo_archive_list` usage_notes and
`vo_schema_describe` are the source of truth. This skill is how you apply them.

## Before writing a query

1. `vo_archive_list` — read the target archive's `usage_notes`; they flag dialect
   deviations and silent traps. Also read the cheatsheet appended to
   `vo_tap_query`'s own tool description.
2. `vo_schema_describe` on the exact table — confirm the table name, the column
   names, and their units. NEVER guess either; most query failures are invented
   columns.
3. Note anything positional: which columns hold RA/Dec and their units.

## Composition rules

- Always `SELECT TOP n` during development; raise or drop TOP only for the final
  run. When the user wants a count, use `COUNT(*)` — don't fetch rows to count them.
- Portable positional idiom (ADQL 2.0):
  `WHERE 1 = CONTAINS(POINT('ICRS', ra_col, dec_col), CIRCLE('ICRS', <ra>, <dec>, <radius_deg>))`
  — but check usage_notes first: some services need a different geometry idiom, and
  what the notes say beats this default.
- Radii and coordinates in decimal degrees unless the schema says otherwise.
- Use table and column names exactly as `vo_schema_describe` returns them.
- One query = one question. Chain simple queries instead of one giant join you
  can't debug.

## Probe → full query

1. **Probe:** `SELECT TOP 5 <needed cols>` with your WHERE clause. Verify the shape
   and values look right.
2. **Sanity-check:** plausible coordinates? expected units? nonzero rows where
   nonzero is expected?
3. **Scale:** raise/drop TOP, or switch to `mode='async'` for large pulls (see the
   `vo-async-results` skill).

## When a query fails

Branch on the error payload — `error_class` + `retry_strategy` — instead of
mutating the query blindly:

- `validation_error` → re-read the message; re-check `vo_schema_describe`; fix the
  named issue only.
- Upstream/service errors → follow `retry_strategy` (retry, back off, or switch
  mode/endpoint as it says).
- Two failures in a row → simplify to the smallest query that should work
  (`SELECT TOP 1 * FROM <table>`), get that passing, then add clauses back one at
  a time.
- An empty result is NOT an error: verify with a broader probe before concluding
  "no data".
