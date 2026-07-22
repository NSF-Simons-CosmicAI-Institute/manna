---
name: vo-async-results
description: Use when a vo_tap_query goes async or returns a job, a result is too
  large to return inline, a cone/SIA result comes back truncated, or the user asks
  about a pending or large query. Covers job polling and delivering results the
  server never returns as bytes.
---

# Async TAP Jobs & Large Results

The server is stateless: it NEVER returns large result bytes. A large result becomes
an async job whose data the CLIENT fetches. Your job is to finish that handoff —
never abandon a job, never claim the data is inaccessible.

## Job lifecycle

1. **Submit:** `vo_tap_query` with `mode='async'` (or `mode='auto'`, which promotes
   an oversize sync result to async on its own). Record the `job_id`.
2. **Poll:** `vo_tap_status` until the phase is terminal (`COMPLETED`, `ERROR`,
   `ABORTED`, `ARCHIVED`). Back off between polls — wait several seconds, longer each round.
   Never burn your whole step budget on back-to-back polls of a QUEUED job.
3. **Fetch pointers:** `vo_tap_results` returns `job_url`, `result_url`, and a
   `fetch_recipe` (runnable pyvo code). It does NOT return the data.
4. **Abandoning a job you submitted?** `vo_tap_abort` cleans it up upstream.

## The handoff (do not skip)

`fetch_recipe.code` is the deliverable. What you do with it depends on your surface:

- **You can execute code** (e.g. a notebook kernel via a Jupyter MCP tool): insert
  and RUN `fetch_recipe.code` in the user's session. The data lands as an astropy
  Table the user can keep working with. Then continue the analysis there.
- **No code-execution surface:** present `result_url` AND the full
  `fetch_recipe.code` to the user as the answer, with one line on how to run it.
  That IS a successful outcome, not a fallback apology.

Never say "I can't access the data". The recipe and URL are the access.

## Narrow vs. go async

- A TAP result oversize under `mode='sync'` → the error tells you to re-run async.
  Do exactly that; don't shrink the science to dodge the async path.
- Cone/SIA results have NO async path: `truncated=true` means narrow the search
  (smaller radius, fewer rows) — the missing rows cannot be fetched later.
- If the user only needs a count or summary, rewrite the query (`COUNT(*)`,
  `SELECT TOP n`, fewer columns) instead of shipping a huge result.

## While a job runs

- Report the phase honestly ("job QUEUED at the archive; polling with backoff").
- If your polling budget runs out, hand over `job_id` + `job_url` and how to check
  later — an unfinished upstream job is a latency outcome, not a failure to hide.
