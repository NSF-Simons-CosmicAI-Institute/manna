# Errors

Every tool returns the same error shape on failure. There is no `isError`
flag; the presence of `error_class` is what a client branches on.

```json
{
  "error_class": "tap_query_error",
  "message": "ERROR: function q3c_radial_query(...) does not exist",
  "retry_strategy": "fix_and_retry",
  "request_id": "c0ffee12",
  "hint": "..."
}
```

`hint` and `retry_after_seconds` are present only when there is something to
say. `request_id` matches the server log line for the failure.

## Error classes

| `error_class` | `retry_strategy` | Raised when |
|---|---|---|
| `validation_error` | `fix_and_retry` | An argument is invalid before any request is made: an unsafe URL, a bad parameter, or `mode="sync"` with a result that must go async |
| `archive_error` | `wait_and_retry` | The archive failed or timed out (HTTP 5xx, connection error, sync timeout) |
| `tap_query_error` | `fix_and_retry` | The archive understood the query and rejected it (bad ADQL, unknown column, unsupported geometry). May carry an error hint from the archive notes |
| `job_not_ready` | `poll` | `get_async_job_results` was called before the job completed; poll `get_async_job_status` |
| `job_gone` | `abandon` | The archive no longer has the job (UWS 404/410). It will not come back; re-submit the query |
| `internal_error` | `abandon` | Anything unexpected inside the server. The message is generic; the cause is in the server log under `request_id` |

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
