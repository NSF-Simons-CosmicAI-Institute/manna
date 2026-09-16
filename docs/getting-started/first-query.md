# Your first query

This page runs MANNA by hand, without an LLM, so you can see what the tools
return before you wire a client in. It uses the MCP Inspector CLI; the
{doc}`../tutorials/index` do the same from Python.

## Start the server

```bash
uvx manna-mcp
curl -s http://localhost:8000/health     # {"status":"ok","version":"..."}
```

## List the tools

```bash
npx -y @modelcontextprotocol/inspector --cli http://localhost:8000/mcp --method tools/list
```

Fifteen tools come back. Each has a description written for an LLM, a JSON
schema for its parameters, and annotations (`readOnlyHint`, `openWorldHint`).
{doc}`../reference/tools` renders the same list.

## Call a tool

```bash
npx -y @modelcontextprotocol/inspector --cli http://localhost:8000/mcp \
  --method tools/call --tool-name resolve_target_name --tool-arg name=M87
```

```text
{"resolved": true, "name": "M87", "ra": 187.7059, "dec": 12.3911, ...}
```

Now a query. ALMA's obscore table supports standard ADQL geometry:

```bash
npx -y @modelcontextprotocol/inspector --cli http://localhost:8000/mcp \
  --method tools/call --tool-name run_adql_query \
  --tool-arg endpoint=https://almascience.eso.org/tap \
  --tool-arg "adql=SELECT TOP 5 obs_id, s_ra, s_dec, band_list FROM ivoa.obscore WHERE CONTAINS(POINT('ICRS', s_ra, s_dec), CIRCLE('ICRS', 187.7059, 12.3911, 0.1)) = 1"
```

The result is an inline envelope:

| Key | Meaning |
|---|---|
| `row_count`, `columns`, `rows` | the data |
| `truncated` | always present, always a boolean; `true` means the archive capped the result at `maxrec` |
| `archive` | short name of the archive the endpoint belongs to, when MANNA has notes for it |
| `query_fingerprint`, `save_recipe`, `load_recipe` | a stable hash of the query and client-side snippets that save the result to `manna_cache/` |
| `next_steps`, `hints` | instructions and tips written for the LLM |

## What an LLM does with it

Given the same question in a chat client, a well-behaved model runs the sequence
MANNA's tool descriptions steer it toward:

1. `resolve_target_name` — coordinates for a named object.
2. `list_archives` — which archive holds the right data, and its endpoint.
3. `describe_table` — table-specific facts before writing ADQL (real column
   names, geometry idiom, enum values).
4. `run_adql_query` — the query; `mode="auto"` promotes an oversize result to
   an async job ({doc}`../guide/large-results`).

The shortcut tools collapse common sequences into one call:
`find_observations_of_target`, `count_observations_near_target`,
`survey_archives_for_target`, and `preview_table`.

## When something goes wrong

Ask Data Lab for the same query with ADQL geometry and it fails, because Data
Lab's TAP passes geometry to PostgreSQL untranslated:

```bash
npx -y @modelcontextprotocol/inspector --cli http://localhost:8000/mcp \
  --method tools/call --tool-name run_adql_query \
  --tool-arg endpoint=https://datalab.noirlab.edu/tap \
  --tool-arg "adql=SELECT TOP 5 ra, dec FROM gaia_dr3.gaia_source WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', 229.022, -0.112, 0.1)) = 1"
```

```json
{"error_class": "tap_query_error", "retry_strategy": "fix_and_retry",
 "message": "...function point(unknown, double precision, double precision) does not exist..."}
```

No `hint` rides this particular payload. This archive note is an *up-front
note*, not an *error hint*: the raw PostgreSQL complaint never suggests the
fix (`q3c_radial_query(ra, dec, <ra0>, <dec0>, <radius_deg>) = 't'`), so the
guidance has to arrive before you write the query, not after it fails — it is
already in `run_adql_query`'s description, in the cheatsheet of archive quirks
({doc}`../reference/tools`). Read that cheatsheet before querying an
unfamiliar archive; it is cheaper than a round trip.

A query an archive understands and rejects for a reason the failure itself
implies — a disallowed ADQL string function, say — gets a real *error hint*
back: an archive note delivered only when a failed query matches its pattern,
riding the payload's `hint` field. Either way, `error_class` and
`retry_strategy` tell the model whether to fix the query, wait, poll, or give
up ({doc}`../reference/errors`).
