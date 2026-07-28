# Modular archives — per-archive knowledge

Status: **implemented** · Version: 0.5.0 · Author: dpg

## 1. Problem

The server's curated knowledge about each archive used to be spread across two
monolithic modules:

- `known_archives.py` — one giant `KNOWN_ARCHIVES` tuple of archive identity
  facts (endpoints, `usage_notes`).
- `schema_kb.py` — one giant `SCHEMA_KB` tuple of per-table `Schema` facts,
  keyed by `(archive, table)` strings.

An archive's knowledge was therefore split across two files, joined by a string
key, and pinned by content assertions scattered through the test suite. Forking
a deployment meant hand-editing both tuples.

We want each archive's knowledge to be **one portable, plugin-style unit** that
can be added or removed like a plugin, per deployment.

## 2. Goals & non-goals

**Goals**

- One archive = one file. Its identity, endpoints, `usage_notes`, and per-table
  `Schema` entries all live together.
- Add an archive → drop a file in `archives/`. Remove one → delete the file. No
  central registry edit, no touching unrelated archives.
- Deployment selection two ways: **physical** (which files ship) and **runtime**
  (`MANNA_ARCHIVES` allowlist from a shared image).
- **Absence ≠ inaccessible.** Dropping an archive removes the server's *claims*
  about it (usage_notes, schema quirks, endpoint examples, cosmetic label),
  never its reachability — it's still reachable via `vo_registry_search` →
  `vo_registry_describe` → `vo_tap_query`.
- Preserve the existing tool contracts and public symbols (`KNOWN_ARCHIVES`,
  `SCHEMA_KB`, `Archive`, `Schema`, the helpers). This is an internal
  reorganization, not an API change.

**Non-goals**

- No move to external data files (YAML/TOML). Archives are Python modules
  (§3.1). The `Archive` dataclass is the seam if that ever changes.
- No RAG / dynamic KB. Still static, in-process, zero-I/O.

## 3. Architecture

### 3.1 Why Python modules, not data files

- The content is **prose-heavy** (`usage_notes` are multi-sentence paragraphs)
  and **structured** (`value_enums` is `dict[str, tuple[...]]`, `cross_refs` is
  `tuple[tuple[str, str], ...]`). Python literals express this cleanly.
- **Static typing + frozen dataclasses** give free validation. A data-file path
  would add a parser, a schema-validation layer, and a dependency.
- Tests **import** archives directly — no fixture loading.

The `Archive` dataclass is the abstraction boundary. A future swap to
data-file- or RAG-backed loading would change only the registry, not consumers.

### 3.2 One model: `Archive`

There is a **single** concept. An archive is one frozen dataclass carrying its
identity, endpoints, `usage_notes`, **its own `schemas`**, and a `priority`.
`Schema` (a table's curated facts) is the only other type — a thing an archive
*has*, not a separate registry. (The earlier design had a separate identity
`Archive` wrapped by an `ArchiveCard` bundle; that split was a migration
artifact and was collapsed — there was no reason for two types once knowledge
is one-file-per-archive.)

```python
# archives/_model.py
@dataclass(frozen=True)
class Schema:
    archive: str            # owning archive short_name (see below)
    table: str
    missing_standard_columns: tuple[str, ...] = ()
    value_enums: dict[str, tuple[str, ...]] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    cross_refs: tuple[tuple[str, str], ...] = ()   # (archive, table) pairs

@dataclass(frozen=True)
class Archive:
    short_name: str
    display_name: str
    host_substrings: tuple[str, ...]
    tap_url: str | None = None
    sia_url: str | None = None
    scs_url: str | None = None
    waveband: str | None = None
    description: str = ""
    notable_tables: tuple[str, ...] = field(default_factory=tuple)
    usage_notes: tuple[str, ...] = field(default_factory=tuple)
    schemas: tuple[Schema, ...] = field(default_factory=tuple)
    priority: int = 100
    def __post_init__(self):   # every schema.archive must equal short_name
        ...
```

`Schema.archive` is redundant with the owning `Archive.short_name`, but kept: it
is part of the `vo_schema_describe` response contract and lets `cross_refs` name
tables as `(archive, table)`. `Archive.__post_init__` enforces the match at
construction, so a hand-built archive can't drift.

`priority` replaces the old "declaration order is load-bearing" convention: the
first TAP-having archives become the endpoint examples shown to the LLM. Bands
(gaps left for inserts): datalab 10, alma 20, nrao 30, eso 40, cadc 50, gaia 60,
gaia_ari 70, sdss 80.

### 3.3 Layout

```
src/manna/
├── archives/
│   ├── __init__.py     # registry: discover_archives() + get_active_archives()
│   ├── _model.py       # Archive, Schema
│   ├── _select.py      # PURE parse_allow / sort / select / validate
│   ├── datalab.py      # ARCHIVE = Archive(...)
│   ├── alma.py … sdss.py
│   ├── _endpoints.py    # endpoint lists + Field descriptions over the active set
│   ├── _knowledge.py    # per-table schema lookups (lookup_schema, active_schema_kb)
```

`Archive`/`Schema` live in `archives/_model.py`; the derived helpers in
`archives/_endpoints.py` and `archives/_knowledge.py` resolve from the active
archive set at call time.

### 3.4 The registry

Pure core + imperative shell, so filtering is testable without env or reload:

```python
# _select.py  (PURE — unit-tested with explicit args)
def parse_allow(raw) -> frozenset[str] | None: ...     # MANNA_ARCHIVES → allow-set (None => all)
def sort_archives(archives): ...                        # by (priority, short_name)
def select_archives(archives, *, allow): ...            # filter; unknown names logged+ignored; empty allowed
def validate_archives(archives): ...                    # unique short_names; unique (archive, table)

# __init__.py  (SHELL)
def discover_archives() -> tuple[Archive, ...]: ...     # import each module's ARCHIVE, validate, sort
@lru_cache(maxsize=1)
def get_active_archives() -> tuple[Archive, ...]: ...   # discover, then narrow by MANNA_ARCHIVES
```

`validate_archives` is cross-archive only (unique short_names, unique
`(archive, table)`); the per-archive "schema belongs to this archive" invariant
is enforced by `Archive.__post_init__`, so it holds for *any* archive, not just
discovered ones. `cross_refs` need NOT resolve within a subset (a pruned
deployment legitimately dangles them); the full-set-resolves invariant is a
test.

`get_active_archives()` is cached like `get_settings()`. Tests reset it with
`get_active_archives.cache_clear()`.

### 3.5 Compat views — a migration bridge, since removed

*Design-history note.* During the split, `known_archives.py`/`schema_kb.py`
survived as thin compat views (`KNOWN_ARCHIVES`, `SCHEMA_KB`, and the helpers
re-exported over the active archive set) so existing consumers kept working
unchanged. Once no consumer imported those symbols, the views were folded into
`archives/_endpoints.py` (endpoint lists + `Field(examples=…)` descriptions, the
`_archive_label` map) and `archives/_knowledge.py` (`lookup_schema` /
`active_schema_kb` / `schema_to_dict`) in 0.5.x, and the two modules were
deleted. Both helpers resolve from the active archive set at call time, so they
honor a mid-process re-selection. Consumers of the derived helpers:

- `_archive_label._STATIC_MAP` — from `host_substring_to_short_name()`.
- `tools/archives.py::vo_archive_list` — iterates `active_archives()`; drops the
  internal `schemas` / `priority` from its envelope (served by
  `vo_schema_describe` / used only for ordering).
- `tools/{tap,sia,cone}.py` — `*_endpoint_description()` / `*_endpoint_urls()`.
- `tools/schema.py::vo_schema_describe` — `lookup_schema()`.

## 4. Deployment selection

1. **Physical** — the active set is bounded by which `archives/*.py` files ship.
   Forking = delete files. Replaces the old "hand-edit two tuples".
2. **Runtime** — `MANNA_ARCHIVES` (comma-separated short_names) narrows the
   discovered set from a shared image:

   ```
   MANNA_ARCHIVES=datalab,alma      # only these two active
   MANNA_ARCHIVES=                  # unset/empty => all discovered
   ```

Optional sugar (future, **not built**): map `MANNA_DEPLOYMENT`
(`local|adl|tacc`) to preset allow-sets when `MANNA_ARCHIVES` is unset —
deliberately deferred until a deployment needs it (a small dict + one branch in
`archives/__init__.py`).

Behavior on odd input (never crash the server): unknown name → logged warning,
ignored; empty result → prominent warning, still boots; duplicate `short_name`
across two files → hard error at load (a dev-time bug).

## 5. Consequence of absence

Archives are **purely additive**. Dropping/deselecting one removes claims, not
reachability:

| Removed with the archive                       | Still works without it |
|------------------------------------------------|------------------------|
| `usage_notes` in `vo_archive_list`             | `vo_tap_query` to any URL |
| `Schema` quirks in `vo_schema_describe`        | `vo_registry_describe` live introspection |
| Endpoint examples in TAP/SIA/SCS tool schemas  | passing the URL explicitly |
| Cosmetic `archive` label on envelopes          | hostname-derived label (`_label_from_host`) |

There is **no fetch/SSRF gating tied to archives.** The 0.4.0 stateless refactor
removed `vo_sia_fetch`, so the old `host_substrings`-derived allow-list has no
consumer; the vestigial `_archive_label.is_known_archive_url()` helper was
dropped once its last caller was gone.

## 6. Testing

```
tests/archives/
├── test_registry.py     # discovery, ordering, integrity, select/validate, MANNA_ARCHIVES narrowing
└── test_<archive>.py     # per-archive content (imports `ARCHIVE` directly; dies with its archive)
```

- **Content** assertions live per-archive (`test_datalab.py` etc.) so deleting
  an archive deletes its test.
- **Structural** assertions (helpers, integrity, `cross_refs` resolve over the
  full set) live in `test_registry.py` and the two `tests/unit/` view tests
  (`test_archive_endpoints.py`, `test_archive_knowledge.py`).
- `EXPECTED_ORDER` in `test_registry.py` pins the shipped membership + order, so
  adding/removing/re-prioritizing an archive forces a conscious test edit.

## 7. Adding / evolving an archive

1. Create `src/manna/archives/<short_name>.py` exporting
   `ARCHIVE = Archive(short_name="…", …, schemas=(Schema(archive="…", …),),
   priority=N)`.
2. Add `tests/archives/test_<short_name>.py` importing `ARCHIVE` and pinning its
   content; add the name to `EXPECTED_ORDER`.
3. `uv run pytest --record-mode=none -q && uv run ruff check .`

Per-archive history is just the git log of its file
(`git log --follow -p archives/nrao.py`), so an archive-knowledge change is a
diff to a single file.

## 8. Future hooks

- **Implemented.** Each `usage_note` / `Schema.notes` entry is now an atomic
  `Note(id, text, audit)` whose co-located `Audit` (a probe or a `manual`
  marker) re-checks the claim — so the archive is the unit of knowledge *and*
  its own regression net. `evals/audit.py` derives the live audit straight from
  the active archives' notes (replacing the retired hand-maintained
  `evals/caveats.py`), and a stale probe prints the exact address to fix,
  `archives/<archive>.py :: <note_id>`. Coverage is a construction invariant: a
  `Note` can't be built without an `Audit`, so every claim is accounted for.
  See `Note`/`Audit` in `archives/_model.py` and `archives/_audit.py`, and the
  offline gate in `tests/archives/test_audits.py`.
- **Implemented.** A `Note` may also carry a `Trap`, which says how the claim is
  *delivered* — because the eval showed reachable knowledge isn't used knowledge
  (issue #57: the NRAO LOWER/UPPER note was true, probed and served by
  `vo_archive_list`, and the model wrote `LOWER()` anyway). A `Trap` without
  `triggers` is *silent*: the model gets no usable correction signal (no error
  at all, or one too cryptic to act on), so the `guidance` is pushed up-front — `archives/_traps.py`
  derives a cheatsheet from the ACTIVE set and `build_mcp()` appends it to
  `vo_tap_query`'s description. That channel is re-sent every turn, so it is
  capped at `CHEATSHEET_TOKEN_BUDGET` (200): if a new trap doesn't fit, write
  terser `guidance` rather than raise the ceiling, and remember `vo_archive_list`
  is still the place for everything that isn't a trap. A `Trap` with `triggers`
  is *loud*: the query throws and the triggers spot the cause in the submitted
  ADQL, so the `guidance` rides the error payload's `hint` and costs nothing
  until it fires. Gated by `tests/archives/test_traps.py` +
  `tests/contracts/test_trap_delivery.py`.
- Structured `Schema` fields (`missing_standard_columns`, `value_enums`) are not
  yet under the audit gate — a documented follow-up. If a structured fact needs
  drift protection, give it a prose `Note` (which then carries an audit).
- `Archive` is the seam for a data-file- or RAG-backed loader if a deployment
  ever needs non-engineer-editable archives.

## 9. Naming

| Thing | Name | Rationale |
|-------|------|-----------|
| The unit | **archive** / `Archive` | one concept; a file IS an archive |
| A table's facts | `Schema` | a thing an archive *has* |
| Package | `archives/` | one module per archive |
| Per-file export | module-level `ARCHIVE` | uniform discovery target |
| Ordering field | `priority` (ascending) | explicit replacement for load-bearing order |
| Runtime knob | `MANNA_ARCHIVES` | matches the `MANNA_*` Settings convention |
| Active-set API | `get_active_archives()` | mirrors `get_settings()` (cached, cache_clear-able) |
