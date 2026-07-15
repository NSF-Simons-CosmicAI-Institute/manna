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
  (`STABLE_ARCHIVES` allowlist from a shared image).
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
src/astro_archives_mcp/
├── archives/
│   ├── __init__.py     # registry: discover_archives() + get_active_archives()
│   ├── _model.py       # Archive, Schema
│   ├── _select.py      # PURE parse_allow / sort / select / validate
│   ├── datalab.py      # ARCHIVE = Archive(...)
│   ├── alma.py … sdss.py
├── known_archives.py   # thin compat view: Archive re-export + KNOWN_ARCHIVES + helpers
├── schema_kb.py        # thin compat view: Schema re-export + SCHEMA_KB + lookup_schema
```

`Archive`/`Schema` live in `archives/_model.py`; `known_archives.py` and
`schema_kb.py` re-export them so every existing
`from astro_archives_mcp.known_archives import Archive` keeps working.

### 3.4 The registry

Pure core + imperative shell, so filtering is testable without env or reload:

```python
# _select.py  (PURE — unit-tested with explicit args)
def parse_allow(raw) -> frozenset[str] | None: ...     # STABLE_ARCHIVES → allow-set (None => all)
def sort_archives(archives): ...                        # by (priority, short_name)
def select_archives(archives, *, allow): ...            # filter; unknown names logged+ignored; empty allowed
def validate_archives(archives): ...                    # unique short_names; unique (archive, table)

# __init__.py  (SHELL)
def discover_archives() -> tuple[Archive, ...]: ...     # import each module's ARCHIVE, validate, sort
@lru_cache(maxsize=1)
def get_active_archives() -> tuple[Archive, ...]: ...   # discover, then narrow by STABLE_ARCHIVES
```

`validate_archives` is cross-archive only (unique short_names, unique
`(archive, table)`); the per-archive "schema belongs to this archive" invariant
is enforced by `Archive.__post_init__`, so it holds for *any* archive, not just
discovered ones. `cross_refs` need NOT resolve within a subset (a pruned
deployment legitimately dangles them); the full-set-resolves invariant is a
test.

`get_active_archives()` is cached like `get_settings()`. Tests reset it with
`get_active_archives.cache_clear()`.

### 3.5 Compat views — consumers barely change

`KNOWN_ARCHIVES = active_archives()` (snapshot at import) and
`SCHEMA_KB = active_schema_kb()` (the active archives' schemas, flattened). The
snapshot feeds import-time machinery (the `_archive_label` map, the
`Field(examples=…)` in tool schemas) so it matches the frozen tool schema; the
two knowledge tools read live accessors (`active_archives()` /
`active_schema_kb()`, via `lookup_schema`) so they honor a mid-process
re-selection. Every current consumer keeps working untouched:

- `_archive_label._STATIC_MAP` — from `host_substring_to_short_name()`.
- `tools/archives.py::vo_archive_list` — iterates `active_archives()`; drops the
  internal `schemas` / `priority` from its envelope (served by
  `vo_schema_describe` / used only for ordering).
- `tools/{tap,sia,cone}.py` — `*_endpoint_description()` / `*_endpoint_urls()`.
- `tools/schema.py::vo_schema_describe` — `lookup_schema()`.

## 4. Deployment selection

1. **Physical** — the active set is bounded by which `archives/*.py` files ship.
   Forking = delete files. Replaces the old "hand-edit two tuples".
2. **Runtime** — `STABLE_ARCHIVES` (comma-separated short_names) narrows the
   discovered set from a shared image:

   ```
   STABLE_ARCHIVES=datalab,alma      # only these two active
   STABLE_ARCHIVES=                  # unset/empty => all discovered
   ```

Optional sugar (future, **not built**): map `STABLE_DEPLOYMENT`
(`local|adl|tacc`) to preset allow-sets when `STABLE_ARCHIVES` is unset —
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
├── test_registry.py     # discovery, ordering, integrity, select/validate, STABLE_ARCHIVES narrowing
└── test_<archive>.py     # per-archive content (imports `ARCHIVE` directly; dies with its archive)
```

- **Content** assertions live per-archive (`test_datalab.py` etc.) so deleting
  an archive deletes its test.
- **Structural** assertions (helpers, integrity, `cross_refs` resolve over the
  full set) live in `test_registry.py` and the two `tests/unit/` view tests
  (`test_known_archives.py`, `test_schema_kb.py`).
- `EXPECTED_ORDER` in `test_registry.py` pins the shipped membership + order, so
  adding/removing/re-prioritizing an archive forces a conscious test edit.

## 7. Adding / evolving an archive

1. Create `src/astro_archives_mcp/archives/<short_name>.py` exporting
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
| Runtime knob | `STABLE_ARCHIVES` | matches the `STABLE_*` Settings convention |
| Active-set API | `get_active_archives()` | mirrors `get_settings()` (cached, cache_clear-able) |
