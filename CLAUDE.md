# astro-archives-mcp — Claude Code context

MCP server exposing IVOA-compliant astronomical archives (NOIRLab Astro Data Lab, NRAO/ALMA, …) to LLM clients. STABLE summer project (CosmicAI). Current version: 0.5.0 (modular per-archive knowledge).

## Commands

```bash
uv sync                                  # install deps + dev deps
uv run pytest --record-mode=none         # 409 tests, offline replay (incl. tests/evals/)
uv run pytest --record-mode=once -k <t>  # re-record one cassette (needs net)
uv run ruff check .                      # lint
uv run python -m astro_archives_mcp      # boot server on :8000 (STABLE_PORT to override)
docker build -t astro-archives-mcp:dev . # container build
npx -y @modelcontextprotocol/inspector --cli http://localhost:8000/mcp --method tools/list
```

Settings env vars are `STABLE_*` (Pydantic Settings, `extra="ignore"`). See `.env.example`.

## Architecture

```
src/astro_archives_mcp/
├── backends/          # TapClient, SiaClient, ConeClient, RegistryClient, ResolverClient
│                      # (typed pyvo/httpx/astropy wrappers — tools never import pyvo directly)
├── tools/
│   ├── tap.py         # vo_tap_query, vo_tap_status, vo_tap_results, vo_tap_abort
│   ├── archives.py    # vo_archive_list
│   ├── schema.py      # vo_schema_describe
│   ├── resolver.py    # vo_target_resolve
│   ├── registry.py    # vo_registry_search, vo_registry_describe
│   ├── cone.py        # vo_cone_search
│   └── sia.py         # vo_sia_search
├── archives/          # per-archive knowledge (one <short_name>.py each)
│   ├── _model.py      # Archive, Schema dataclasses (leaf)
│   ├── _select.py     # pure parse_allow/sort/select/validate helpers
│   ├── __init__.py    # registry: discover_archives() + get_active_archives()
│   ├── _endpoints.py  # endpoint lists/descriptions over the active set (Field examples, label map)
│   ├── _knowledge.py  # per-table schema lookups (lookup_schema, active_schema_kb, schema_to_dict)
│   └── <archive>.py   # ARCHIVE = Archive(..., schemas=(...), priority=N)
├── _serialization.py  # shared dataclass → JSON-friendly dict helper
├── shaper.py          # astropy.Table → inline envelope; oversize → result-URL/fetch_recipe
├── errors.py          # ToolExecutionError taxonomy + error_to_payload (spec §7)
├── job_store.py       # in-memory async TAP job registry (job_url directory, no bytes)
├── observability.py   # JSON logging + current_request_id ContextVar
├── app.py             # build_mcp() + build_app() factories; RequestIdMiddleware
└── __main__.py        # uvicorn entry; called by `python -m astro_archives_mcp`
```

Knowledge layer — **per-archive modules** (`archives/<short_name>.py`, see docs/archives-spec.md):
- Each archive is one portable, plugin-style file: a single `Archive` dataclass carrying its identity (URLs, waveband), `usage_notes`, **its own per-table `Schema` entries**, and a `priority`. One archive = one file, exporting `ARCHIVE = Archive(...)`.
- Derived helpers over the active archive set live in the package: **`archives/_endpoints.py`** (endpoint URL lists + Field-example descriptions, the `_archive_label` substring map) and **`archives/_knowledge.py`** (`lookup_schema` / `active_schema_kb` / `schema_to_dict`). Both resolve from the `lru_cache`d `get_active_archives()` at call time — no import-time snapshot. Archive-level quirks live in `usage_notes` (surfaced by `vo_archive_list`); table-specific facts live in `Archive.schemas` (surfaced by `vo_schema_describe`), NOT in usage_notes.
- **Archives are additive, never gating.** A missing archive just means no curated claims about it; it stays reachable via `vo_registry_search`. Selection: delete archive files, or set `STABLE_ARCHIVES=datalab,alma` (unset ⇒ all). `priority` (ascending) sets order.

Result handling (stateless — the server never persists result bytes):
- **Small results inline.** A TAP/cone/SIA result within the inline caps (`STABLE_INLINE_ROW_LIMIT` / `STABLE_INLINE_BYTE_LIMIT`) is returned inline via `shape_inline_table`.
- **Large TAP results go async.** `vo_tap_query` mode='auto' re-submits an oversize sync result as an async job; mode='sync' raises `validation_error` telling the LLM to use mode='async'. `vo_tap_results` returns the upstream `job_url` + `result_url` + a **pyvo `fetch_recipe`** (`shape_result_url`) — the client loads the data itself (anonymous only). This is why there is no `result_store` or MCP Resource serving: designed for multi-tenant TACC where per-user byte caches don't scale.
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

- **Tools never touch raw pyvo.** Only `backends/` imports pyvo. Verifiable with `grep -r pyvo src/astro_archives_mcp/tools/`.
- **The server never persists result bytes.** No result cache, no MCP Resource serving. Large results are handed to the client as a `job_url` + `result_url` + pyvo `fetch_recipe`; the client fetches them itself. This is the load-bearing multi-tenant invariant — do NOT reintroduce a server-side byte store.
- **`truncated` is always a top-level boolean.** Never silently true. The ALMA_MCP prototype's `df.head(20)` is the explicit anti-pattern. Enforced in `shape_inline_table`.
- **Error payloads carry `error_class` + `retry_strategy`.** `error_class` is the discriminator the LLM branches on. No `isError` key (intentional — see `tools/tap.py` docstring).
- **Tokens / raw tracebacks never reach the LLM.** `InternalError.redact_message = True` (ClassVar) drives `error_to_payload` to swap in `_INTERNAL_GENERIC_MESSAGE`. Server logs retain the cause via `__cause__`.

## Forking for a deployment

Two ways to shape which archives make curated claims (see docs/archives-spec.md):
- **Physical** — delete unwanted `archives/<short_name>.py` files. Discovery picks up whatever remains; no other file needs touching (its `Schema` entries live in the same file).
- **Runtime** — set `STABLE_ARCHIVES=datalab,alma` (comma-separated short_names) to narrow a shared image without deleting files. Unset/empty ⇒ every archive active.

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
