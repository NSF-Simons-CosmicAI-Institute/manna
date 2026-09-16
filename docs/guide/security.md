# Security

MANNA is designed to be one shared server process serving many LLM sessions.
The guarantees below are what
make that safe enough; the last section says what is still open.

## Nothing is kept between requests

The server holds no result cache, no job registry, and no session map. An
async job is addressed by the archive's own `job_url`, and every status,
results, or abort call goes to the archive live. A shared process therefore
has nothing one session could read of another's. (An earlier design had a
process-global job store keyed by server-side ids; it was removed because,
without per-user authentication, any session could read or abort any job.)

Result bytes are never persisted or re-served. A large result is handed back
as a `result_url` plus a pyvo recipe the client runs itself.

## Every user-supplied URL is checked before it is fetched

Tool arguments that name a URL — `endpoint` on the TAP, cone, and SIA tools,
`ivoid_or_url` on `describe_ivoa_service` when it is not an `ivo://`
identifier, and `job_url` on the async tools — pass through one guard before
any request is made. The guard:

1. requires an `http` or `https` scheme (no `file:`, `ftp:`, `data:`);
2. requires a host;
3. if `MANNA_ALLOWED_HOSTS` is set, requires the host to match it (exact or
   subdomain);
4. resolves the host and requires every address to be public — no private,
   loopback, link-local, or reserved space.

Rule 4 is what stops a caller from pivoting the server into its own network
(`http://hub:8000`, `169.254.169.254`). Rule 3 is for locked-down deployments
willing to give up registry discovery for a tighter blast radius. `abort_async_job`
sends an upstream `DELETE`, so the guard is load-bearing there, not advisory.

Known residual risk: DNS rebinding. The guard resolves the name and the HTTP
library resolves it again when connecting, so a hostile authoritative server
can answer differently the second time. Closing it needs a pinned-address
transport, which is deliberately out of scope so far.

## Errors never leak internals

Unexpected exceptions become `error_class: internal_error` with a fixed
generic message and a `request_id`. The real exception is logged server-side
with that id; tokens and tracebacks never reach the model. Archive-originated
errors keep their upstream message, because the model needs it to fix the
query.

## The MCP endpoint has no authentication

`/mcp/` accepts any caller that can reach it. That is the root of the findings
still open from the 2026-07 review: a caller who can guess another user's
`job_url` can read or abort that job at the archive, because the archive's
UWS endpoint is anonymous too. A deployment mitigates by binding to loopback and letting only trusted
local clients reach the port. Per-caller state keyed on a verified identity
is the proper fix and is not implemented.

## Read-only by declaration

Every tool declares `readOnlyHint: true` except `abort_async_job`
(`destructiveHint: true`, `idempotentHint: true`). Tools that reach live
services declare `openWorldHint: true`; `list_archives` reads only the
in-process archive notes.
