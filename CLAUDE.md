# MANNA — Claude Code context

MANNA (MCP Architecture for NOIRLab and NRAO Archives) is an MCP server exposing
IVOA-compliant astronomical archives (NOIRLab Astro Data Lab, NRAO/ALMA, …) to LLM
clients. STABLE summer project (CosmicAI). Current version: 0.6.2 (stateless
query-cache envelopes).

**Casing:** *MANNA* in prose; lowercase `manna` for every identifier — package,
`python -m manna`, `src/manna`, image tags, and the MCP client alias. Never
uppercase an identifier. Exception: the PyPI distribution is `manna-mcp` (bare
`manna` is admin-prohibited on PyPI); the import package and CLI stay `manna`.

## Commands

```bash
uv sync                                  # install deps + dev deps
uv run pytest --record-mode=none         # 682 tests, offline replay (incl. tests/evals/)
uv run pytest --record-mode=once -k <t>  # re-record one cassette (needs net)
uv run ruff check .                      # lint
uv run python -m manna                   # boot server on :8000 (MANNA_PORT to override)
docker build -t manna:dev .              # container build
npx -y @modelcontextprotocol/inspector --cli http://localhost:8000/mcp --method tools/list
```

Settings env vars are `MANNA_*` (Pydantic Settings, `extra="ignore"`). See `.env.example`.

## Architecture

```
src/manna/
├── backends/          # TapClient, SiaClient, ConeClient, RegistryClient, ResolverClient
│                      # (typed pyvo/httpx/astropy wrappers — tools never import pyvo directly)
├── tools/
│   ├── tap.py                # vo_tap_query, vo_tap_status, vo_tap_results, vo_tap_abort
│   ├── archives.py           # vo_archive_list
│   ├── schema.py             # vo_schema_describe
│   ├── resolver.py           # vo_target_resolve
│   ├── registry.py           # vo_registry_search, vo_registry_describe
│   ├── cone.py               # vo_cone_search
│   ├── sia.py                # vo_sia_search
│   ├── find_observations.py  # vo_find_observations (cross-archive: resolve -> pick archive -> SIA/cone)
│   ├── count.py               # vo_count_observations
│   ├── survey.py              # vo_survey_target
│   ├── inspect.py             # vo_inspect_table
│   ├── _select.py             # shared resolve + archive-selection helpers for count/survey/find facades
│   └── _constants.py          # shared tool-layer constants (_ERROR_DOCSTRING)
├── archives/          # per-archive knowledge (one <short_name>.py each)
│   ├── _model.py      # Archive, Schema dataclasses (leaf)
│   ├── _select.py     # pure parse_allow/sort/select/validate helpers
│   ├── __init__.py    # registry: discover_archives() + get_active_archives()
│   ├── _endpoints.py  # endpoint lists/descriptions over the active set (Field examples)
│   ├── _knowledge.py  # per-table schema lookups (lookup_schema, active_schema_kb, schema_to_dict)
│   ├── _audit.py      # Audit dataclass: declarative live-probe spec read by evals/audit.py
│   ├── _traps.py      # trap push channels (silent cheatsheet + loud failure-time hint)
│   └── <archive>.py   # ARCHIVE = Archive(..., schemas=(...), priority=N)
│                      # (currently: alma.py, cadc.py, datalab.py, eso.py, gaia.py, gaia_ari.py, nrao.py, sdss.py)
├── _archive_label.py  # archive short_name lookup from a URL (label field on envelopes)
├── _url_guard.py      # SSRF guard: scheme + public-address check on every user-supplied URL
├── config.py          # Settings (MANNA_* env, extra="ignore") + get_settings() singleton
├── _serialization.py  # shared dataclass → JSON-friendly dict helper
├── shaper.py          # astropy.Table → inline envelope; oversize → result-URL/fetch_recipe
├── errors.py          # ToolExecutionError taxonomy + error_to_payload (spec §7)
├── observability.py   # JSON logging + current_request_id ContextVar
├── app.py             # build_mcp() + build_app() factories; RequestIdMiddleware
└── __main__.py        # uvicorn entry; called by `python -m manna`
```

Knowledge layer — **per-archive modules** (`archives/<short_name>.py`, see docs/archives-spec.md):
- Each archive is one portable, plugin-style file: a single `Archive` dataclass carrying its identity (URLs, waveband), `usage_notes`, **its own per-table `Schema` entries**, and a `priority`. One archive = one file, exporting `ARCHIVE = Archive(...)`.
- Derived helpers over the active archive set live in the package: **`archives/_endpoints.py`** (endpoint URL lists + Field-example descriptions) and **`archives/_knowledge.py`** (`lookup_schema` / `active_schema_kb` / `schema_to_dict`). The `_archive_label` substring map itself lives in top-level **`_archive_label.py`**, built from `_endpoints.host_substring_to_short_name()`. Both resolve from the `lru_cache`d `get_active_archives()` at call time — no import-time snapshot. `_archive_label.py`'s `_STATIC_MAP` is different: it is built once at import, so a restart is needed to pick up a newly added archive. Archive-level quirks live in `usage_notes` (surfaced by `vo_archive_list`); table-specific facts live in `Archive.schemas` (surfaced by `vo_schema_describe`), NOT in usage_notes.
- **Archives are additive, never gating.** A missing archive just means no curated claims about it; it stays reachable via `vo_registry_search`. Selection: delete archive files, or set `MANNA_ARCHIVES=datalab,alma` (unset ⇒ all). `priority` (ascending) sets order.

Result handling (stateless — the server never persists result bytes):
- **Small results inline.** A TAP/cone/SIA result within the inline caps (`MANNA_INLINE_ROW_LIMIT` / `MANNA_INLINE_BYTE_LIMIT`) is returned inline via `shape_inline_table`.
- **Successful TAP/cone/SIA envelopes carry `query_fingerprint` + `save_recipe`** (`attach_cache_fields` in shaper.py): a stable hash of the query identity plus a client-side snippet that saves the result to `manna_cache/<fingerprint>.csv` and appends a row to `manna_cache/catalog.csv`. The server computes and forgets — saving happens in the client's environment; reuse policy lives in the deployment persona, not here.
- **Large TAP results go async.** `vo_tap_query` mode='auto' re-submits an oversize sync result as an async job; mode='sync' raises `validation_error` telling the LLM to use mode='async'. `vo_tap_results` returns the upstream `job_url` + `result_url` + a **pyvo `fetch_recipe`** (`shape_result_url`) — the client loads the data itself (anonymous only). This is why there is no `result_store` or MCP Resource serving: designed for multi-tenant TACC where per-user byte caches don't scale.
- **Async jobs are addressed by their upstream `job_url`, not a server-side id.** There is no JobStore. `vo_tap_status` / `vo_tap_results` / `vo_tap_abort` all take `job_url` and hit the archive live. A job the archive has dropped surfaces as `job_gone` (`retry_strategy=abandon`) via the upstream 404/410 — that status is the *only* liveness signal, since nothing is tracked locally.
- **Large cone/SIA results truncate inline** with `truncated=true` — there's no async job to promote to, so the LLM is told to narrow the search.

Tests mirror the source: `tests/unit/` (pure), `tests/archives/` (registry mechanics + one `test_<archive>.py` of content assertions per archive — deleting an archive deletes its test), `tests/backends/` (vcrpy cassettes), `tests/tools/` (in-memory MCP Client), `tests/contracts/` (tool schema + error envelope invariants), `tests/workflows/` (multi-tool chains), `tests/app/` (Starlette via httpx ASGITransport).

## Gotchas (real things that bit us — don't repeat)

- **vcrpy `decode_content` shim lives at `tests/conftest.py`.** Do NOT move it to a subdirectory — pytest doesn't propagate conftests across siblings, and `tests/tools/` + `tests/backends/` both need it (astropy's votable parser passes `decode_content=True` which vcrpy's stub forwards to BytesIO, which rejects it).
- **FastMCP lifespan MUST be propagated to Starlette.** `Starlette(..., lifespan=mcp_app.lifespan)`. Without it, every `POST /mcp` raises `RuntimeError(StreamableHTTPSessionManager task group was not initialized)`. The in-memory `Client(mcp_server)` bypasses Starlette, so this only shows up over HTTP. Regression guarded by `tests/app/test_build_app.py`.
- **Dockerfile uses `uv sync --frozen --no-dev --no-editable`.** The `--no-editable` is load-bearing — the default editable install bakes `/build/src` paths into the venv, which break in the `/app/` runtime stage.
- **`README.md` is NOT in `.dockerignore`.** uv reads `pyproject.toml`'s `readme=` during install. Resist the shrink-the-build-context instinct.
- **`POST /mcp` 307-redirects to `/mcp/`** because of Starlette `Mount`. Inspector follows redirects; bare `curl /mcp` does not. Use `curl -L` or `/mcp/`.
- **Default for replay is `--record-mode=none`.** New cassettes need explicit `--record-mode=once -k <test>` + network access.
- **NRAO obscore requires `mode='async'`.** The `/sync` TAP endpoint returns 5xx on data reads against `tap_schema.obscore`. Metadata queries (`tap_schema.tables`, `tap_schema.columns`) work in sync. This is encoded in `archives/nrao.py`.

## Reliability contracts (don't break)

- **Tools never touch raw pyvo.** Only `backends/` imports pyvo. Verifiable with `grep -r pyvo src/manna/tools/`.
- **The server never persists result bytes.** No result cache, no MCP Resource serving. Large results are handed to the client as a `job_url` + `result_url` + pyvo `fetch_recipe`; the client fetches them itself. This is the load-bearing multi-tenant invariant — do NOT reintroduce a server-side byte store.
- **The server holds NO cross-request state at all.** The JobStore was removed in the stateless-async-tap change: it was a process-global `dict` with no notion of caller identity, so in a shared-service topology (one server process, many users, no per-user auth) any session holding any `job_id` could read or abort another user's job. It also concealed nothing, because the promotion envelope already returned the `job_url`. Do NOT reintroduce a server-side job registry, cache, or session map; if you need per-caller state, it must be keyed on a verified caller identity, which this server does not yet have.
- **Every user-supplied URL clears `_url_guard.ensure_safe_url` before it is fetched.** `endpoint` (tap/cone/sia), `ivoid_or_url` (registry, when not an `ivo://` IVOID), and `job_url` (status/results/abort). The guard rejects non-http(s) schemes and any target resolving to private/loopback/link-local/reserved space, which is what stops a caller pivoting to `http://hub:8000` or `169.254.169.254` from inside the compose network. `vo_tap_abort` sends an upstream DELETE, so this is load-bearing, not advisory. Known gap: DNS rebinding (we resolve, then `requests` resolves again) — see the module docstring.
- **`truncated` is always a top-level boolean.** Never silently true. The ALMA_MCP prototype's `df.head(20)` is the explicit anti-pattern. Enforced in `shape_inline_table`.
- **Error payloads carry `error_class` + `retry_strategy`.** `error_class` is the discriminator the LLM branches on. No `isError` key (intentional — the shared `_ERROR_DOCSTRING` in `tools/_constants.py`, appended to every tool's docstring, spells this out).
- **Tokens / raw tracebacks never reach the LLM.** `InternalError.redact_message = True` (ClassVar) drives `error_to_payload` to swap in `_INTERNAL_GENERIC_MESSAGE`. Server logs retain the cause via `__cause__`.

## Forking for a deployment

Two ways to shape which archives make curated claims (see docs/archives-spec.md):
- **Physical** — delete unwanted `archives/<short_name>.py` files. Discovery picks up whatever remains; no other file needs touching (its `Schema` entries live in the same file).
- **Runtime** — set `MANNA_ARCHIVES=datalab,alma` (comma-separated short_names) to narrow a shared image without deleting files. Unset/empty ⇒ every archive active.

A dropped/deselected archive removes only the server's *claims* about it — never its reachability (still works via `vo_registry_search`).

## Git flow

Three branch kinds:

- **`main`** — stable. Only updated by merging from `dev`. Do NOT commit feature work directly.
- **`dev`** — integration target. All feature PRs land here.
- **`<initials>/<feature-name>`** — feature branches. Dan uses `dpg/`. Example: `dpg/slice-d-schema-knowledge`.

Workflow per change:

1. `git checkout dev && git pull origin dev`
2. `git checkout -b dpg/<feature-name>`
3. Implement, test, lint.
4. `gh pr create --base dev` once tests + ruff pass locally. CI runs ruff + pytest + container build + Inspector smoke.
5. Merge to `dev` when green.
6. Periodically open a PR `dev → main` to promote a stable cut.
