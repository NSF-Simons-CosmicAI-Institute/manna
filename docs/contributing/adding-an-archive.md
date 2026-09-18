# Adding an archive

An archive in MANNA is one Python file under `src/manna/archives/` that
exports a single `ARCHIVE` object: the archive's identity, its endpoints,
its archive notes, and the checks that re-verify those notes. Archives are
additive and never gating: dropping the file removes only MANNA's *claims*
about the archive, never the model's ability to reach it through
`search_ivoa_registry`. This page is the procedure; the design record is
{doc}`archives-spec` and the user-facing overview is {doc}`../guide/archives`.

## Before you write anything

Learn the archive through the server's own tools before writing a line of
the archive file. The in-memory client needs no running server:

```python
from fastmcp import Client
from manna.app import build_mcp

client = Client(build_mcp())


def payload(result):
    return result.structured_content
```

Work through these, in order, and write down what you find.

1. **Endpoints.** `search_ivoa_registry(keywords=["<archive name>"])` lists
   the archive's registered services; `describe_ivoa_service(ivoid_or_url=
   "<tap url>", table_filter="<keyword>")` lists its tables. Note the TAP
   URL and, if present, the SIA and cone-search URLs. Many archives register
   several TAP services; pick the one whose tables you will curate.
2. **Does sync work?** Run three queries with `run_adql_query(..., mode="sync")`:
   a `tap_schema.tables` lookup, a `tap_schema.columns` lookup on the table
   you care about, and a `SELECT TOP 1 ...` data read with a positional
   filter. Metadata queries almost always work in sync. If the data read
   returns an `archive_error` timeout, that is your first archive note (see
   ALMA's `unfiltered-scan-timeout` and NRAO's async-only note).
3. **Which geometry?** Try the standard ADQL form,
   `CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', ra0, dec0, r)) = 1`,
   as a `COUNT(*)`. If it errors, try the archive's native form (Data Lab
   needs `q3c_radial_query`). The working form becomes the archive's
   `CountTarget` geometry.
4. **Tables that matter.** Two or three at most. For each, the columns a
   model will filter on, any column whose values are a small controlled
   vocabulary, and any column whose meaning is not obvious from its name.
5. **Facts a model gets wrong.** Three to five things that produce a wrong
   answer or an unhelpful error unless the model is told first: rows finer
   than the object of interest (ALMA), a geometry the archive does not
   translate (Data Lab), a table at a non-standard name (NRAO), a flag column
   that must be filtered to get real sources. Each becomes a `Note`; the
   ones that fail silently become up-front notes.

Keep the ADQL you ran. Every note you write needs a check, and the queries
you just ran are those checks.

## The file

Create `src/manna/archives/<short_name>.py`. The `short_name` is the
filename, the token a deployment puts in `MANNA_ARCHIVES`, the `archive`
argument to `describe_table` and `preview_table`, the `archive` label on
result envelopes, and the key in `list_archives`. Use lowercase letters,
digits, and underscores only, and keep it short: `datalab`, `alma`,
`gaia_ari`.

The module docstring is the archive's display name. The file imports only
from `manna.archives._model`, `manna.archives._audit`, and
`manna.archives._count`, and defines one module-level name:

```python
"""Example Archive."""

from manna.archives._audit import Audit
from manna.archives._count import ContainsPoint, CountTarget
from manna.archives._model import Archive, Note, Pitfall, Schema

ARCHIVE = Archive(
    short_name="example",
    ...
)
```

Discovery (`manna.archives.discover_archives`) imports every module in the
package that does not start with an underscore and takes its `ARCHIVE`.
Nothing registers the file anywhere else.

## Field reference

Every field of every dataclass an archive is built from. "Surfaces as" says
where the model sees the value. The validation column quotes the condition
that raises at construction, so a mistake fails at import, not at query time.

### `Archive`

| Field | Type | Default | Read by | Surfaces as | Validation |
|---|---|---|---|---|---|
| `short_name` | `str` | required | discovery, `MANNA_ARCHIVES`, `describe_table`, `preview_table`, envelope labels | `list_archives.archives[].short_name`; the `archive` field on every envelope from this archive | must be unique across shipped archives (`validate_archives`, ValueError) |
| `display_name` | `str` | required | tool descriptions (endpoint examples) | `list_archives.archives[].display_name`; the name beside each example endpoint URL in `run_adql_query`'s description | none |
| `host_substrings` | `tuple[str, ...]` | required | `_archive_label` (label lookup on any URL) | the `archive` label on envelopes for any URL containing one of these substrings | none; pick substrings that match only this archive's hosts |
| `tap_url` | `str or None` | `None` | endpoint examples, `preview_table`, `count_observations_near_target`, checks | `list_archives.archives[].tap_url`; one of the two example URLs in `run_adql_query`'s `endpoint` description if this archive is among the first two by priority with a TAP URL | none |
| `sia_url` | `str or None` | `None` | `find_observations_of_target(service="image")`, `search_images_by_position` examples | `list_archives.archives[].sia_url`; SIA example URL | none |
| `scs_url` | `str or None` | `None` | `find_observations_of_target(service="catalog")`, `search_catalog_by_position` examples | `list_archives.archives[].scs_url`; cone-search example URL | none |
| `waveband` | `str or None` | `None` | `list_archives(waveband=...)`, the workflow tools' `waveband` filter | `list_archives.archives[].waveband`; compared case-insensitively as a whole string, so use the vocabulary already shipped: `optical`, `millimeter`, `radio`, `multi`, `infrared` | none |
| `description` | `str` | `""` | `list_archives` | `list_archives.archives[].description`; two or three sentences on what the archive holds and which services it exposes | none |
| `notable_tables` | `tuple[str, ...]` | `()` | `list_archives` | `list_archives.archives[].notable_tables`; the tables a model should reach for first, fully qualified | none |
| `usage_notes` | `tuple[Note, ...]` | `()` | `list_archives`, the cheatsheet, the check runner | `list_archives.archives[].usage_notes[]` as plain text; a note carrying an up-front pitfall also lands in `run_adql_query`'s description | every element must be a `Note` (TypeError) |
| `schemas` | `tuple[Schema, ...]` | `()` | `describe_table`, `preview_table`, the check runner | `describe_table` for `(short_name, table)`; NOT echoed by `list_archives` | every `Schema.archive` must equal this `short_name` (ValueError); `(archive, table)` pairs unique across shipped archives (ValueError) |
| `count_target` | `CountTarget or None` | `None` | `count_observations_near_target`, `survey_archives_for_target` | the archive appears in survey results and is a candidate for the count tool; `None` means the archive is skipped by both | none |
| `priority` | `int` | `100` | discovery sort key `(priority, short_name)` | order of `list_archives`; which archives become endpoint examples (first two with the URL); which archive the workflow tools pick first | none; shipped values are datalab 10, alma 20, nrao 30, eso 40, cadc 50, gaia 60, gaia_ari 70, sdss 80 |
| `paused` | `str or None` | `None` | `select_archives` at startup | absent from every tool surface unless named in `MANNA_ARCHIVES`; the reason is logged at boot | `None` or a non-blank string (ValueError) |

### `Note`

One atomic claim. A note is the unit the check runner re-verifies, so keep
each note to a single fact.

| Field | Type | Default | Read by | Surfaces as | Validation |
|---|---|---|---|---|---|
| `id` | `str` | required | the check runner's report, tests | never shown to the model; the address a failed check prints | non-empty (ValueError); unique within the archive (`test_audits.py`) |
| `text` | `str` | required | `list_archives` (usage notes) or `describe_table` (schema notes) | the note's prose, verbatim | non-empty (ValueError) |
| `audit` | `Audit` | required | `evals/audit.py` | never shown; see the `Audit` table | must be an `Audit` instance (TypeError) |
| `pitfall` | `Pitfall or None` | `None` | `_pitfalls.py` | see the `Pitfall` table | `Pitfall` or `None` (TypeError) |

### `Audit`

The check (called `Audit` in the code) is the falsifiable half of a note.
It carries no network code; `evals/audit.py` executes it. Build one with a
constructor, not the bare class: `Audit.probe`, `Audit.count`, or
`Audit.manual`.

| Constructor | Fields set | `expect` values | Use it for |
|---|---|---|---|
| `Audit.probe(expect=..., adql=...)` | `expect`, `adql` | `ok` (query succeeds), `error` (query must fail), `empty` (succeeds with zero rows), `nonempty` (succeeds with at least one row) | a claim one ADQL statement confirms or refutes |
| `Audit.count(table=..., columns=...)` | `expect="count"`, `adql` (via `has_cols`), `columns` | `count` (every named column must be present in `tap_schema.columns`) | a claim that certain columns exist |
| `Audit.manual(reason)` | `expect="manual"`, `reason` | `manual` | a claim no single query can check: download recipes, naming conventions, timeout behaviour, mirror equivalence |

| Field | Type | Default | Validation |
|---|---|---|---|
| `expect` | `str` | required | one of `ok`, `error`, `empty`, `nonempty`, `count`, `manual` (ValueError) |
| `adql` | `str` | `""` | required for every `expect` except `manual`, which must NOT carry it (ValueError) |
| `columns` | `tuple[str, ...]` | `()` | required and non-empty for `count` (ValueError) |
| `reason` | `str` | `""` | required and non-empty for `manual` (ValueError) |

Two helpers write common probes: `has_table(table)` returns the ADQL for a
`tap_schema.tables` lookup, meant to be paired with `expect="nonempty"`, and
`has_cols(table, columns)` is what `Audit.count` uses internally.

### `Pitfall`

A pitfall opts a note into a push channel. The channel is decided entirely
by whether `triggers` is set.

| Field | Type | Default | Read by | Surfaces as | Validation |
|---|---|---|---|---|---|
| `guidance` | `str` | required | `_pitfalls.py` | up-front note: one line in the cheatsheet block at the end of `run_adql_query`'s description, keyed to the archive's TAP host; error hint: the `hint` field on a failed query's error envelope | non-empty (ValueError) |
| `triggers` | `tuple[str, ...]` | `()` | `Pitfall.fires_on` | empty means up-front note; non-empty means error hint, fired when any trigger appears (case-insensitive) in the submitted ADQL | none |

Choose the channel by asking whether the model can self-correct from the
failure. If the wrong query returns a plausible answer with no error (ALMA's
`COUNT(*)` over-count) or an error that never names the fix (Data Lab's
`function point(...) does not exist`), the model needs the fact before it
queries: use an up-front note. If the query fails and the ADQL that caused it
is recognisable (NRAO's `LOWER(`), an error hint costs nothing until it
fires. The cheatsheet is re-sent every turn, so every up-front note pays rent:
`CHEATSHEET_TOKEN_BUDGET` is 200 tokens across all active archives and
`tests/archives/test_pitfalls.py` fails the build when it is exceeded. Keep
`guidance` to one terse, imperative sentence. It is the fix, not the note's
full prose.

### `Schema`

Archive notes about one table. `describe_table(archive, table)` merges this
with the live `tap_schema` columns.

| Field | Type | Default | Read by | Surfaces as | Validation |
|---|---|---|---|---|---|
| `archive` | `str` | required | `describe_table`, `validate_archives` | `describe_table.archive` | must equal the owning `Archive.short_name` (ValueError) |
| `table` | `str` | required | `describe_table`, `preview_table` | `describe_table.table`; match the archive's own casing (`ivoa.ObsCore` at ESO, `ivoa.obscore` at ALMA) | `(archive, table)` unique across shipped archives (ValueError) |
| `missing_standard_columns` | `tuple[str, ...]` | `()` | `describe_table` | `describe_table.missing_standard_columns`; ObsCore columns the table lacks | none |
| `value_enums` | `dict[str, tuple[str, ...]]` | `{}` | `describe_table`, `preview_table` | `describe_table.value_enums`; the exact values a controlled-vocabulary column takes, as strings | none |
| `notes` | `tuple[Note, ...]` | `()` | `describe_table`, the cheatsheet, the check runner | `describe_table.notes[]`; a schema note with an up-front pitfall also reaches the cheatsheet | every element a `Note` (TypeError) |
| `cross_refs` | `tuple[tuple[str, str], ...]` | `()` | `describe_table` | `describe_table.cross_refs`, pairs of `(archive, table)` that hold related data | every pair must name a `Schema` shipped by some archive (`test_registry.py`, full set only; a subset deployment may dangle) |

### `CountTarget`

How to count observations near a position at this archive. Declared on the
archive, read by `count_observations_near_target` and
`survey_archives_for_target`, which render
`SELECT <count_expr> AS n FROM <table> WHERE <predicate>`.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `table` | `str` | required | the countable table, fully qualified |
| `geometry` | `Q3CRadial`, `ContainsPoint`, or `IntersectsRegion` | required | the spatial predicate builder, below |
| `count_expr` | `str` | `"COUNT(*)"` | override when rows are finer than the thing being counted: ALMA uses `COUNT(DISTINCT member_ous_uid)` |
| `mode` | `"sync"`, `"auto"`, or `"async"` | `"sync"` | `sync` when the count answers within the sync timeout; `auto` to try sync and promote on timeout; `async` for archives whose data reads only work as jobs |

| Geometry | Constructor | Predicate rendered | Use at |
|---|---|---|---|
| `ContainsPoint` | `ContainsPoint(ra_col, dec_col)` | `CONTAINS(POINT('ICRS', ra_col, dec_col), CIRCLE('ICRS', ra, dec, r)) = 1` | any archive that implements ADQL geometry (Gaia, ESO, NRAO obscore; also the IRSA example below) |
| `IntersectsRegion` | `IntersectsRegion(region_col="s_region")` | `INTERSECTS(CIRCLE('ICRS', ra, dec, r), region_col) = 1` | footprint columns, so mosaics whose centre lies outside the circle still match (ALMA) |
| `Q3CRadial` | `Q3CRadial(ra_col, dec_col)` | `q3c_radial_query(ra_col, dec_col, ra, dec, r) = 't'` | q3c-indexed PostgreSQL archives that do not translate ADQL geometry (Data Lab) |

<!-- part two -->
