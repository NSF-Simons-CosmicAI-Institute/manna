# Concepts

MANNA is organised in four layers. The names below are the ones used in the
MANNA paper; the code identifiers differ in places, and the table at the end
maps them.

## Connections

Tools that call the standard IVOA interfaces directly:

| Interface | Tools |
|---|---|
| TAP / ADQL | `run_adql_query`, `get_async_job_status`, `get_async_job_results`, `abort_async_job` |
| SIA 2.0 (images) | `search_images_by_position` |
| SCS (cone search) | `search_catalog_by_position` |
| RegTAP (the IVOA registry) | `search_ivoa_registry`, `describe_ivoa_service` |
| Sesame (name resolution) | `resolve_target_name` |

Connections are thin: each is a typed wrapper over pyvo or httpx in
`manna.backends`. Tools never import pyvo themselves.

## Workflow tools

One call for a task that would otherwise take several:

- `find_observations_of_target` — resolve a name or coordinates, pick an
  archive by service and waveband, run the SIA or cone search.
- `count_observations_near_target` — resolve, pick an archive, run a `COUNT`.
- `survey_archives_for_target` — per-archive counts for one target.
- `preview_table` — columns, curated notes, and a sample of rows for one table.

Workflow tools exist because small models get a multi-step chain wrong more
often than a single call. They compose the same connections and archive notes
an LLM could call itself.

## Result handling

Small results come back inline. A result larger than the inline caps is not
squeezed into the response: a TAP result is re-submitted as an async job whose
result the client fetches itself, and a cone or SIA result is truncated inline
with `truncated: true`. Successful results also carry a query fingerprint and
a client-side save recipe. {doc}`large-results` has the details.

The server keeps nothing between requests: no result cache, no job registry,
no session map. Every async job is addressed by its upstream `job_url`.

## Archive notes

One Python file per archive (`src/manna/archives/<short_name>.py`) holding its
endpoints, waveband, usage notes, and per-table schema facts. Every note is a
`Note` with a **check** — a live probe or a manual marker that re-verifies the
claim — so notes do not silently rot.

A note that describes a known way queries go wrong is a **pitfall**. Pitfalls
reach the model through two channels:

- an **up-front note** is injected into the `run_adql_query` description every
  turn (the block is called the cheatsheet);
- an **error hint** rides on the `hint` field of a failed query's error payload,
  only when the failure matches the pitfall's trigger pattern.

Archive notes are additive, never gating: an archive MANNA has no notes for is
still reachable through `search_ivoa_registry`. {doc}`archives` explains how
the active set is chosen; {doc}`../contributing/archives-spec` explains how to
write one.

## Names in the code

| Paper term | In the code |
|---|---|
| Connections | `manna.backends` (`TapClient`, `SiaClient`, `ConeSearchClient`, `RegistryClient`, `ResolverClient`) |
| Workflow tools | `manna.tools.workflows`, plus `preview_table` in `manna.tools.inspect` |
| Result handling | `manna.results` (`shape_*`, "envelope", "promotion") |
| Archive notes | `manna.archives.<name>`, `Note`, `Schema` |
| Check | `Audit` |
| Pitfall | `Pitfall` (`Note.pitfall`) |
| Up-front note | `Pitfall.channel == "upfront"`, `upfront_note_cheatsheet()` |
| Error hint | `Pitfall.channel == "error_hint"`, `error_hint_for()` |
