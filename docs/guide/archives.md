# Archives

MANNA ships archive notes for these archives (`src/manna/archives/`), listed
here in `priority` order (the order `list_archives` and the workflow tools'
archive selection use):

| short_name | Archive | Waveband |
|---|---|---|
| `datalab` | NOIRLab Astro Data Lab | optical |
| `alma` | ALMA Science Archive | millimeter |
| `nrao` | NRAO Science Data Archive — **paused** | radio |
| `eso` | ESO Science Archive | optical |
| `cadc` | Canadian Astronomy Data Centre | multi |
| `gaia` | ESA Gaia Archive | optical |
| `gaia_ari` | Gaia ARI Heidelberg | optical |
| `sdss` | Sloan Digital Sky Survey | optical |

`list_archives` returns the active ones with their endpoints, usage notes, and
notable tables; `describe_table` returns per-table facts. Each archive is one
file, so adding one is dropping a file in and deleting one is removing it
({doc}`../contributing/archives-spec`).

## The active set

Which archives make curated claims is decided at startup:

- **Unset** `MANNA_ARCHIVES` (the default): every archive file present, except
  paused ones.
- `MANNA_ARCHIVES=datalab,alma`: only those two. An unknown name is logged as
  a warning and ignored rather than crashing the server, so a typo silently
  drops that archive instead of stopping startup — check the server log if an
  archive you named is missing.
- **Paused** archives (`Archive.paused = "<reason>"`) ship in the package but
  stay out of the default set. Naming one in `MANNA_ARCHIVES` activates it:
  `MANNA_ARCHIVES=datalab,alma,nrao`.

`nrao` has been paused since 2026-09-11 at NRAO's request while its TAP
service is rebuilt. When active, its obscore data reads need
`mode="auto"` or `mode="async"`; the archive notes say so.

`priority` (ascending) orders archives in `list_archives` and in the workflow
tools' archive selection.

## Absence is not inaccessibility

Dropping or deselecting an archive removes only MANNA's *claims* about it:
its usage notes, schema facts, endpoint examples, and the `archive` label on
envelopes. The archive is still reachable: `search_ivoa_registry` finds it,
`describe_ivoa_service` introspects it, and `run_adql_query` queries it. The
active set narrows what the model is told, not where it may go. (Where it may
go is the job of `MANNA_ALLOWED_HOSTS`; see {doc}`security`.)

## Forking for a deployment

- **Physical** — delete unwanted `src/manna/archives/<short_name>.py` files
  from your fork. Discovery picks up whatever remains.
- **Runtime** — keep the shared image and set `MANNA_ARCHIVES` per
  deployment.
