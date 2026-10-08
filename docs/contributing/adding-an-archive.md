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
6. **Images and cone services.** If the registry listed an SIA or cone-search
   URL, call `search_images_by_position` or `search_catalog_by_position` at a
   bright target once to confirm the service answers and note which SIA
   version it speaks; those URLs become `sia_url` and `scs_url`.

Write down the endpoints, the waveband, the host substrings that identify
this archive's URLs, the tables, and the facts. Keep the ADQL you ran. Every
note you write needs a check, and the queries you just ran are those checks.

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

Each geometry constructor above takes these fields:

| Field | Type | Default | Used by |
|---|---|---|---|
| `ra_col` | `str` | required | `Q3CRadial`, `ContainsPoint` |
| `dec_col` | `str` | required | `Q3CRadial`, `ContainsPoint` |
| `region_col` | `str` | `"s_region"` | `IntersectsRegion` |

## Worked example: an IRSA archive

This section builds an archive for NASA/IPAC's IRSA TAP service around the
AllWISE source catalogue, one stage at a time. Stages 1 to 3 are complete
listings, each replacing the previous one; stages 4 and 5 show only the lines
that change. The facts in it were checked live on 2026-09-18 and read "at the
time of writing" for a reason: archives change, which is why every note
carries a check. `irsa` is an example and is **not shipped** in MANNA; copy
the pattern, not the file. Shipping an archive is a curation commitment:
someone owns its notes, runs its checks when they drift, and answers for what
the model is told. This one has no owner.

Reconnaissance found: TAP at `https://irsa.ipac.caltech.edu/TAP`; the table
`allwise_p3as_psd` with columns `designation`, `ra`, `dec`, `w1mpro`,
`w2mpro`, `cc_flags`, `ext_flg`, `ph_qual`; `CONTAINS(POINT(...),
CIRCLE(...))` works and a `COUNT(*)` over a 0.05 degree circle answers in
sync in under a second; a `SELECT TOP 1` data read on the same table timed
out on sync after 20 seconds, so row reads belong in `mode="auto"`;
`q3c_radial_query` fails with `ORA-00904: "Q3C_RADIAL_QUERY": invalid
identifier` (IRSA is Oracle-backed).

### Stage 1: identity and endpoints

```python
"""NASA/IPAC Infrared Science Archive (IRSA)."""

from manna.archives._model import Archive

ARCHIVE = Archive(
    short_name="irsa",
    display_name="NASA/IPAC Infrared Science Archive",
    host_substrings=("irsa.ipac",),
    tap_url="https://irsa.ipac.caltech.edu/TAP",
    waveband="infrared",
    description=(
        "Infrared catalogues and images from WISE, 2MASS, Spitzer, and "
        "other NASA infrared missions, served over a single TAP service "
        "with one table per catalogue release."
    ),
    notable_tables=("allwise_p3as_psd",),
    priority=90,
)
```

This already works: drop it in, and `list_archives` shows it last (priority
90 sorts after `sdss` at 80), its TAP URL is a valid `endpoint`, and any
envelope from a URL containing `irsa.ipac` is labelled `irsa`.

### Stage 2: usage notes with checks

One note of each check kind.

```python
"""NASA/IPAC Infrared Science Archive (IRSA)."""

from manna.archives._audit import Audit, has_table
from manna.archives._model import Archive, Note

ARCHIVE = Archive(
    short_name="irsa",
    display_name="NASA/IPAC Infrared Science Archive",
    host_substrings=("irsa.ipac",),
    tap_url="https://irsa.ipac.caltech.edu/TAP",
    waveband="infrared",
    description=(
        "Infrared catalogues and images from WISE, 2MASS, Spitzer, and "
        "other NASA infrared missions, served over a single TAP service "
        "with one table per catalogue release."
    ),
    notable_tables=("allwise_p3as_psd",),
    usage_notes=(
        Note(
            id="allwise-default-table",
            text=(
                "For WISE sources start with allwise_p3as_psd, the AllWISE point-source catalogue."
            ),
            audit=Audit.probe(expect="nonempty", adql=has_table("allwise_p3as_psd")),
        ),
        Note(
            id="sync-row-reads-time-out",
            text=(
                "Row reads (SELECT TOP N ... with or without a cone) on "
                "allwise_p3as_psd time out on /sync; aggregates such as "
                "COUNT(*) over a small cone return in under a second. Run "
                "row reads with mode='auto', which promotes to an async job "
                "on timeout."
            ),
            audit=Audit.manual(
                "Timeout-under-load behaviour observed 2026-09-18; not "
                "deterministically probeable without a slow live scan."
            ),
        ),
        Note(
            id="quality-flag-columns",
            text=(
                "cc_flags marks contamination and confusion artifacts "
                "(one character per band, '0' = clean); ext_flg marks "
                "extended sources; ph_qual is the per-band photometric "
                "quality letter. Filter cc_flags = '0000' for reliable "
                "point sources."
            ),
            audit=Audit.count(table="allwise_p3as_psd", columns=("cc_flags", "ext_flg", "ph_qual")),
        ),
    ),
    priority=90,
)
```

`Audit.probe` with `has_table` re-checks the table exists; `Audit.count`
re-checks the three columns exist; `Audit.manual` records why the timeout
claim cannot be probed. Every claim that a check can falsify should get a
probe or a count; reserve `manual` for claims that need many rows, several
endpoints, or a client-side flow.

### Stage 3: a schema

Per-table facts go on a `Schema`, not in `usage_notes`. `describe_table
("irsa", "allwise_p3as_psd")` and `preview_table` read this.

```python
"""NASA/IPAC Infrared Science Archive (IRSA)."""

from manna.archives._audit import Audit, has_table
from manna.archives._model import Archive, Note, Schema

ARCHIVE = Archive(
    short_name="irsa",
    display_name="NASA/IPAC Infrared Science Archive",
    host_substrings=("irsa.ipac",),
    tap_url="https://irsa.ipac.caltech.edu/TAP",
    waveband="infrared",
    description=(
        "Infrared catalogues and images from WISE, 2MASS, Spitzer, and "
        "other NASA infrared missions, served over a single TAP service "
        "with one table per catalogue release."
    ),
    notable_tables=("allwise_p3as_psd",),
    usage_notes=(
        Note(
            id="allwise-default-table",
            text=(
                "For WISE sources start with allwise_p3as_psd, the AllWISE point-source catalogue."
            ),
            audit=Audit.probe(expect="nonempty", adql=has_table("allwise_p3as_psd")),
        ),
        Note(
            id="sync-row-reads-time-out",
            text=(
                "Row reads (SELECT TOP N ... with or without a cone) on "
                "allwise_p3as_psd time out on /sync; aggregates such as "
                "COUNT(*) over a small cone return in under a second. Run "
                "row reads with mode='auto', which promotes to an async job "
                "on timeout."
            ),
            audit=Audit.manual(
                "Timeout-under-load behaviour observed 2026-09-18; not "
                "deterministically probeable without a slow live scan."
            ),
        ),
        Note(
            id="quality-flag-columns",
            text=(
                "cc_flags marks contamination and confusion artifacts "
                "(one character per band, '0' = clean); ext_flg marks "
                "extended sources; ph_qual is the per-band photometric "
                "quality letter. Filter cc_flags = '0000' for reliable "
                "point sources."
            ),
            audit=Audit.count(table="allwise_p3as_psd", columns=("cc_flags", "ext_flg", "ph_qual")),
        ),
    ),
    schemas=(
        Schema(
            archive="irsa",
            table="allwise_p3as_psd",
            value_enums={
                # 0 = point source; 1-5 = increasing association with a
                # 2MASS extended source.
                "ext_flg": ("0", "1", "2", "3", "4", "5"),
            },
            notes=(
                Note(
                    id="magnitudes-are-vega",
                    text=(
                        "w1mpro..w4mpro are profile-fit magnitudes in the Vega "
                        "system; w1sigmpro..w4sigmpro are their uncertainties. "
                        "A NULL magnitude means no detection in that band."
                    ),
                    audit=Audit.count(
                        table="allwise_p3as_psd",
                        columns=("w1mpro", "w2mpro"),
                    ),
                ),
            ),
            cross_refs=(),
        ),
    ),
    priority=90,
)
```

`cross_refs` names `(archive, table)` pairs at other shipped archives that
hold related data, for example ALMA's `ivoa.obscore` lists
`("nrao", "tap_schema.obscore")`. Leave it empty unless the relation is
real; on the full shipped set every pair must resolve to an existing
`Schema` (`tests/archives/test_registry.py`).

### Stage 4: a pitfall

The `cc_flags` fact fails silently: a `COUNT(*)` that ignores it returns a
plausible number with no error, so the model needs it before it queries.
That is an up-front note: a `Pitfall` with no `triggers`.

```python
        Note(
            id="quality-flag-columns",
            text=(
                "cc_flags marks contamination and confusion artifacts "
                "(one character per band, '0' = clean); ext_flg marks "
                "extended sources; ph_qual is the per-band photometric "
                "quality letter. Filter cc_flags = '0000' for reliable "
                "point sources."
            ),
            audit=Audit.count(table="allwise_p3as_psd", columns=("cc_flags", "ext_flg", "ph_qual")),
            pitfall=Pitfall(
                guidance=(
                    "cc_flags marks artifacts; filter cc_flags = '0000' or "
                    "counts include spurious detections."
                ),
            ),
        ),
```

Add `Pitfall` to the `_model` import. The guidance line now appears in
`run_adql_query`'s description under the cheatsheet header, keyed to
`irsa.ipac.caltech.edu`, for every turn of every conversation. Run
`uv run pytest tests/archives/test_pitfalls.py` to confirm the cheatsheet is
still within its 200-token budget. That test runs on the default active set;
if a paused archive may return, also run it with `MANNA_ARCHIVES` set to
every archive, since a re-enabled archive's up-front notes count too.

For comparison, an error hint recognises the failing ADQL and rides the
error envelope instead. NRAO's is the shipped example:

```python
            pitfall=Pitfall(
                guidance=(
                    "NRAO's TAP rejects the ADQL string functions LOWER()/UPPER()/ILIKE "
                    "and the || concatenation operator. Re-run without them: match exact "
                    "case (instrument_name = 'GBT') or use a LIKE pattern."
                ),
                triggers=("LOWER(", "UPPER(", "ILIKE", "||"),
            ),
```

### Stage 5: a count target

The reconnaissance showed the standard geometry works and a cone `COUNT(*)`
answers in sync, so the archive can take part in
`count_observations_near_target` and `survey_archives_for_target`:

```python
from manna.archives._count import ContainsPoint, CountTarget

    ...
    count_target=CountTarget(
        table="allwise_p3as_psd",
        geometry=ContainsPoint("ra", "dec"),
        count_expr="COUNT(*)",
        mode="sync",
    ),
    priority=90,
)
```

Had the count also timed out, `mode="auto"` would try sync and promote on
timeout, and the survey tool would report the archive as `pending` with a
`job_url` when its polling budget ran out.

## Wiring it in

Every file that changes when an archive is added, with the edit.

| File | Edit |
|---|---|
| `src/manna/archives/<short_name>.py` | new; the file above |
| `tests/archives/test_<short_name>.py` | new; content assertions for this archive, template below |
| `tests/archives/test_registry.py` | insert `"<short_name>"` into `EXPECTED_ORDER` at the position `(priority, short_name)` sorts it to; `irsa` at priority 90 goes last |
| `docs/guide/archives.md` | add a row to the archives table in priority order |
| `docs/archives-spec.md` | append the archive to the priority list in §3.2 (`datalab 10, alma 20, … sdss 80`) |
| `CLAUDE.md` | add `<short_name>.py` to the `currently:` list under `archives/` in the architecture tree |
| `README.md` | only if the archive belongs in the one-line list of archives in the opening sentence |

The per-archive test pins the facts a reviewer would otherwise re-derive.
Mirror `tests/archives/test_gaia.py`:

```python
"""Content assertions for the IRSA archive."""

from manna.archives._count import ContainsPoint, CountTarget
from manna.archives.irsa import ARCHIVE


def test_irsa_identity():
    assert ARCHIVE.short_name == "irsa"
    assert ARCHIVE.tap_url == "https://irsa.ipac.caltech.edu/TAP"
    assert "irsa.ipac" in ARCHIVE.host_substrings


def test_irsa_usage_notes_cover_the_default_table_and_quality_flags():
    notes = " ".join(n.text for n in ARCHIVE.usage_notes).lower()
    assert "allwise_p3as_psd" in notes
    assert "cc_flags" in notes


def test_irsa_key_note_audit_expectations():
    notes = {n.id: n for n in ARCHIVE.usage_notes}
    assert notes["allwise-default-table"].audit.expect == "nonempty"
    assert notes["quality-flag-columns"].audit.expect == "count"


def test_irsa_quality_flag_note_is_an_upfront_note():
    note = next(n for n in ARCHIVE.usage_notes if n.id == "quality-flag-columns")
    assert note.pitfall is not None
    assert note.pitfall.channel == "upfront"


def test_irsa_count_target():
    ct = ARCHIVE.count_target
    assert isinstance(ct, CountTarget)
    assert ct.table == "allwise_p3as_psd"
    assert ct.geometry == ContainsPoint("ra", "dec")
    assert ct.mode == "sync"
```

Nothing else needs an edit, because these derive from discovery at call
time:

- the `archive` label map in `_archive_label.py` (built from
  `host_substrings` once at import, so restart a running server);
- the example endpoint URLs in `run_adql_query`, `search_images_by_position`,
  and `search_catalog_by_position` descriptions (the first two active
  archives by priority that have that URL);
- the cheatsheet in `run_adql_query`'s description (every up-front pitfall
  on every active archive);
- `evals/audit.py` (walks every note of every archive);
- `list_archives`, `describe_table`, `preview_table`, and the workflow
  tools' archive selection.

## Verify

Run these in order from the repo root.

1. `uv run pytest --record-mode=none -q` — offline. Four failures to
   expect on a first attempt: `test_discover_finds_every_shipped_archive`
   when `EXPECTED_ORDER` was not updated or the priority sorts the new name
   somewhere else; `Duplicate Schema entry` when two archives declare the
   same `(archive, table)`; `test_cheatsheet_stays_within_the_token_budget`
   when a new up-front note pushes the block past 200 tokens (shorten the
   `guidance`, do not raise the budget); and a test that pins a waveband
   filter to one archive (`tests/tools/test_list_archives.py::test_list_archives_filter_by_waveband`
   expects `millimeter` to return only `alma`) when your archive shares that
   waveband.
2. `uv run ruff check . && uv run ruff format --check .` — CI also runs
   `pyright` over `src/`, so the archive file must type-check too (the
   dataclass constructors are fully typed; a wrong field type fails there).
3. `uv sync --group eval && uv run python -m evals.audit --archive <short_name>` —
   live, needs network. Every `probe` and `count` check runs against the
   archive; `manual` rows are listed, not run. A failed check names the note
   `id` so you can go straight to it.
4. See it through a tool: with the in-memory client, `list_archives(short_name=
   "<short_name>")` returns the archive with its notes, and `describe_table
   (archive="<short_name>", table="<table>")` returns `known: True` with the
   schema notes and value enums. Or start the server and use the Inspector
   (see {doc}`../getting-started/first-query`).
5. If you changed `docs/guide/archives.md`, build the site:
   `uv run sphinx-build -W --keep-going -j auto -b html docs docs/_build/html`.

## Evolving an archive

- **Changing a note.** Keep the `id` stable; it is the address in check
  reports and in any test that looks the note up by id. Change the `text`,
  and if the claim changed, change the check to match. Re-run the checks for
  that archive.
- **Adding a note.** One fact per note. Decide whether it fails silently (up-
  front note), fails recognisably (error hint), or is reachable knowledge
  (plain note). Add a check.
- **Adding a table.** A new `Schema` with `archive=` equal to the owning
  `short_name`. If it is the table a model should start with, add it to
  `notable_tables` too.
- **Changing priority.** This reorders `list_archives`, may change which
  archives appear as example endpoints, changes which archive the workflow
  tools try first, and moves the name inside `EXPECTED_ORDER`.
- **Referencing another archive.** A `cross_refs` pair must name a `Schema`
  that some shipped archive declares; the full-set test fails otherwise.
- **Endpoint moved.** Change the URL, and add or change a `host_substrings`
  entry if the host changed, or envelopes from the new host will carry a
  hostname-derived label instead of the `short_name`.

Per-archive history is the git log of one file:
`git log --follow -p src/manna/archives/<short_name>.py`.

## Pausing and un-pausing

Pause an archive when its service is being rebuilt or asks for less traffic
and you want to keep the notes for when it returns. The archive stays in the
package and is discoverable, but is out of the default active set.

1. Set `paused` on the archive to a dated reason ending with the re-enable
   instruction, following the shipped wording:
   `paused="Paused YYYY-MM-DD at <who>'s request: <reason>; set MANNA_ARCHIVES to a list that includes '<short_name>' to re-enable."`
2. Add the name to `PAUSED` in `tests/archives/test_registry.py`.
3. Check the default tool surface no longer steers at it. The contract test
   `tests/contracts/test_no_paused_archive_steering.py` pins that no tool
   name, description, or parameter example mentions the paused archive's
   name or host; extend its forbidden pattern if you pause a second archive.
4. Tests that need the archive's content opt in with a fixture that widens
   `MANNA_ARCHIVES` (see `nrao_active` in `tests/conftest.py`), listed before
   `mcp_server` so the cheatsheet is built with the archive active.
5. Tag eval tasks that need it with `requires_archive: <short_name>` in
   `evals/tasks.yaml` so they are skipped, not failed, while it is paused.
6. The archive notes page ({doc}`../guide/archives`) says which archives are
   paused; update it.
7. `CLAUDE.md` tags the paused archive in its architecture tree
   (`nrao.py [paused]`) and states when and why it was paused; update both.

To un-pause: delete the `paused=` field, remove the name from `PAUSED`,
re-point or delete the steering contract test, and update the guide. The
`requires_archive` tags become no-ops and may stay. A deployment can turn a
paused archive on at any time by naming it in `MANNA_ARCHIVES`; pausing is a
default, not a lock.

## Removing an archive

1. Delete `src/manna/archives/<short_name>.py` and
   `tests/archives/test_<short_name>.py`.
2. Remove the name from `EXPECTED_ORDER` (and `PAUSED` if it was paused).
3. Remove its row from `docs/guide/archives.md` and its entry in `CLAUDE.md`.
4. Search the other archives for `cross_refs` that named one of its tables
   and remove them; the full-set test will find any you miss.
5. Run the suite.

The archive stays reachable: `search_ivoa_registry` still finds it and
`run_adql_query` still queries it. Only MANNA's claims about it are gone.

## Checklist

```text
[ ] reconnaissance: endpoints, sync behaviour, geometry, tables, 3-5 facts
[ ] src/manna/archives/<short_name>.py exporting ARCHIVE
[ ]   every Note has a check; silent failures carry an up-front Pitfall
[ ]   Schema per curated table, archive= matches short_name
[ ]   CountTarget if a positional COUNT works
[ ] tests/archives/test_<short_name>.py
[ ] EXPECTED_ORDER in tests/archives/test_registry.py
[ ] docs/guide/archives.md table row
[ ] CLAUDE.md archives/ list
[ ] uv run pytest --record-mode=none -q
[ ] uv run ruff check .
[ ] uv run ruff format --check .
[ ] uv run python -m evals.audit --archive <short_name>
[ ] list_archives / describe_table show it
[ ] restart any running server (label map is built at import)
```
