# Errors

Every tool returns the same error shape on failure. There is no `isError`
flag; the presence of `error_class` is what a client branches on.

```json
{
  "error_class": "tap_query_error",
  "message": "ERROR: function q3c_radial_query(...) does not exist",
  "retry_strategy": "fix_and_retry",
  "request_id": "a1b2c3d4e5f6",
  "hint": "..."
}
```

`hint` is present only when there is something to say. `retry_after_seconds`
is defined on the payload but no error currently sets it. `request_id` is a
12-character hex string (`uuid4().hex[:12]`) matching the server log line for
the failure; it is present in HTTP mode only — under `--stdio` there is no
request-id middleware, so the field is absent.

## Error classes

The table below is each class's *default* `retry_strategy`. A few call sites
override it for a specific failure — see "Overrides" below — so always read
`retry_strategy` off the payload rather than assuming it from `error_class`.

| `error_class` | `retry_strategy` (default) | Raised when |
|---|---|---|
| `validation_error` | `fix_and_retry` | An argument is invalid before any request is made: a malformed URL scheme, a missing host, a bad parameter, or `mode="sync"` with a result that must go async |
| `archive_error` | `wait_and_retry` | The archive failed or timed out (HTTP 5xx, connection error, sync timeout) |
| `tap_query_error` | `fix_and_retry` | The archive understood the query and rejected it (bad ADQL, unknown column, unsupported geometry). May carry an error hint from the archive notes |
| `job_not_ready` | `poll` | `get_async_job_results` was called before the job completed; poll `get_async_job_status` |
| `job_gone` | `abandon` | The archive no longer has the job (UWS 404/410). It will not come back; re-submit the query |
| `internal_error` | `abandon` | Anything unexpected inside the server. The message is generic; the cause is in the server log under `request_id` |

**Overrides:**

- `_url_guard.ensure_safe_url` raises `validation_error` with `retry_strategy="abandon"`, not `fix_and_retry`, for a host outside `MANNA_ALLOWED_HOSTS`, a host that cannot be resolved, or a host that resolves to a non-public address — none of those can be fixed by changing the call. Only a bad scheme or an empty host stay `fix_and_retry`.
- `backends/registry.py` raises `archive_error` with `retry_strategy="abandon"` for an IVOID the registry has never heard of.
- `tools/tap.py`'s `get_async_job_results` and `workflows/count.py`'s async count polling both raise `validation_error` with `retry_strategy="abandon"` when the job phase is `ABORTED` — there is nothing to retry, the job is dead.

## Retry strategies

| `retry_strategy` | What the model should do |
|---|---|
| `fix_and_retry` | Change the arguments and call again |
| `wait_and_retry` | Wait (`retry_after_seconds` if present) and call again unchanged |
| `poll` | Call `get_async_job_status(job_url)` until `phase` is `COMPLETED`, then retry |
| `abandon` | Stop; the call cannot succeed as made |

## Error hints

When a `tap_query_error` matches a pitfall in the archive notes, the fix rides
back in `hint`. This is the *error hint* channel: it exists because a model
that had already read the same advice in `list_archives` still wrote the wrong
idiom, and the error payload is the one thing it reliably reads at failure
time ({doc}`../guide/concepts`).

## Python

The classes behind these payloads are in {py:mod}`manna.errors`
({doc}`python-api`).
