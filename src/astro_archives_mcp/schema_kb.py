"""Compatibility view over the per-table schema knowledge in the registry.

The curated per-table facts now live inside each archive
(`archives/<short_name>.py`, in `Archive.schemas`), so a table's knowledge
sits next to its archive's usage_notes. This module preserves the historical
public surface:

- `Schema` — re-exported from `archives._model` (so existing imports work).
- `SCHEMA_KB` — every active archive's schemas flattened, snapshotted at import.
- `active_schema_kb()` — the same, resolved live from the active set.
- `lookup_schema` / `schema_to_dict` — unchanged behavior.

`Schema` stores table-specific SURPRISES only — missing standard columns,
value enums for filterable fields, spatial index columns, naming conventions.
Archive-level quirks (ADQL bugs, endpoint routing, mode requirements) belong
in the archive's `usage_notes`, NOT here.

To add a table's knowledge: append a `Schema(...)` to the owning archive's
`schemas`. To retire an archive's knowledge entirely: delete its module.
See docs/archives-spec.md.
"""

from typing import cast

from astro_archives_mcp._serialization import dataclass_to_jsonable_dict
from astro_archives_mcp.archives import get_active_archives
from astro_archives_mcp.archives._model import Note, Schema, note_texts

__all__ = [
    "SCHEMA_KB",
    "Schema",
    "active_schema_kb",
    "lookup_schema",
    "schema_to_dict",
]


def active_schema_kb() -> tuple[Schema, ...]:
    """Every active archive's schemas, flattened in registry order (live)."""
    return tuple(schema for archive in get_active_archives() for schema in archive.schemas)


# Snapshot at import — equal to active_schema_kb() at process start. Consumed
# by tests and any import-time reader; runtime lookups go through the live
# accessor below so a mid-process re-selection is honored.
SCHEMA_KB: tuple[Schema, ...] = active_schema_kb()


def lookup_schema(*, archive: str, table: str) -> Schema | None:
    """Linear scan of the active schema KB. None if no curated entry.

    Matching is exact (case-sensitive) on both archive short_name and
    table name. Same shape as known_archives.by_short_name.
    """
    for s in active_schema_kb():
        if s.archive == archive and s.table == table:
            return s
    return None


def schema_to_dict(s: Schema) -> dict:
    """Serialize a Schema for inclusion in a tool's JSON envelope."""
    d = dataclass_to_jsonable_dict(s)
    # s.notes is Note-only by the time __post_init__ has run (_normalize_notes
    # coerces every element); the field type stays wider only to admit the
    # migration-scaffold str form at construction.
    d["notes"] = note_texts(cast(tuple[Note, ...], s.notes))  # Notes → LLM-facing text
    return d
