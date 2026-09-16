# Large results

MANNA never stores result bytes and never serves them later. That single rule
shapes everything on this page. It is what lets one server process serve many
users on shared infrastructure without a per-user byte cache.

## Inline caps

A tabular result is returned inline when it is within both caps:

| Setting | Default |
|---|---|
| `MANNA_INLINE_ROW_LIMIT` | 200 rows |
| `MANNA_INLINE_BYTE_LIMIT` | 49152 bytes (48 KiB) |

The defaults suit a small-context local model. For Claude, raise them
(`MANNA_INLINE_ROW_LIMIT=2000`, `MANNA_INLINE_BYTE_LIMIT=262144`).

An inline envelope always carries a top-level `truncated` boolean. It is never
silently true: if the archive capped the result at `maxrec`, `truncated` is
`true` and `truncation_reason` says so.

## TAP: promotion to an async job

`run_adql_query` has three modes:

- `sync` — TAP `/sync` only. An oversize result raises `validation_error`
  telling the caller to use `async`; a timeout is an `archive_error`.
- `async` — submit to TAP `/async` and return a **promotion envelope** at once.
- `auto` (default) — try `/sync`; on timeout or an oversize result, re-submit
  as an async job and return the promotion envelope.

A promotion envelope:

```json
{
  "mode": "async",
  "job_url": "https://almascience.eso.org/tap/async/1234",
  "phase": "EXECUTING",
  "submitted_at": "2026-09-15T14:02:11+00:00",
  "archive": "alma",
  "next_steps": [
    "Poll get_async_job_status(job_url) until phase is COMPLETED or ERROR — pass back the job_url from this response, verbatim.",
    "When COMPLETED, call get_async_job_results(job_url) to get the result_url and a fetch_recipe.",
    "Then execute the fetch_recipe code with your code-execution tool to load the data — do not abandon the job or re-submit the query."
  ],
  "fetch_recipe": {"module": "pyvo", "code": "import pyvo\njob = pyvo.dal.AsyncTAPJob('https://.../async/1234')\ntable = job.fetch_result().to_table()"}
}
```

The job is addressed by its upstream `job_url`. There is no server-side job id
and no registry: `get_async_job_status`, `get_async_job_results`, and
`abort_async_job` all take `job_url` and talk to the archive live. A job the
archive has dropped comes back as `error_class: job_gone` with
`retry_strategy: abandon`; because nothing is tracked locally, that upstream
status is the only liveness signal.

When the job completes, `get_async_job_results` returns the result **URL** and
a **fetch recipe**, not the rows:

```json
{
  "phase": "COMPLETED",
  "job_url": "https://almascience.eso.org/tap/async/1234",
  "result_url": "https://almascience.eso.org/tap/files/result_1234.xml",
  "format": "votable",
  "archive": "alma",
  "next_steps": [
    "The query already ran and its full result is ready — do NOT re-run it. Execute the Python in fetch_recipe.code with your code-execution tool (e.g. run it in a notebook cell); it loads the result as an astropy Table named `table`.",
    "If `import pyvo` fails, execute fetch_recipe.alternative instead — it needs only astropy.",
    "Only if you cannot execute code at all: re-run run_adql_query with a narrower query (SELECT TOP N, tighter WHERE, or aggregates like COUNT/GROUP BY) so the result fits inline."
  ],
  "fetch_recipe": {"module": "pyvo", "code": "import pyvo\n..."}
}
```

The client runs the recipe in its own Python environment. In a notebook that
is a cell; in Claude Code it is a `python` invocation. The data lands in the
client's session as an `astropy.table.Table` named `table`. Anonymous archives
only: the recipe carries no credentials.

## Cone and SIA: truncate inline

There is no async job to promote a cone or SIA search to, so an oversize result
is truncated inline with `truncated: true`, and the LLM is told to narrow the
search (smaller radius, a band filter, a lower `maxrec`).

## Query fingerprint and save recipe

Every successful TAP, cone, or SIA envelope carries:

- `query_fingerprint` — a stable 12-hex hash of the query identity (tool,
  endpoint, query text or position, limits), the same across runs and
  versions;
- `save_recipe` — a client-side snippet that writes the result to
  `manna_cache/<fingerprint>.csv` and appends a row to `manna_cache/catalog.csv`
  (columns: `fingerprint, tool, endpoint, archive, query, target, n_rows, truncated, maxrec, csv_path, saved_at`).

Inline sync TAP results also carry `load_recipe`, whose `code` re-runs the
query with pyvo *and* saves it, so a client that runs one cell gets both the
data and the cache row.

The server computes the fingerprint and forgets it. Whether a client reuses a
cached result is that client's policy; the Astro Data Lab deployment's persona,
for example, checks `catalog.csv` before re-running a matching query
({doc}`../deployments/astro-data-lab`).
