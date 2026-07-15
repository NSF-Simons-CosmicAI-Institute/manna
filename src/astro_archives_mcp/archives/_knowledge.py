"""Per-table schema lookups over the active archive set (was schema_kb.py)."""

from astro_archives_mcp._serialization import dataclass_to_jsonable_dict
from astro_archives_mcp.archives import get_active_archives
from astro_archives_mcp.archives._model import Schema, note_texts

__all__ = ["active_schema_kb", "lookup_schema", "schema_to_dict"]


def active_schema_kb() -> tuple[Schema, ...]:
    """Every active archive's schemas, flattened in registry order."""
    return tuple(schema for archive in get_active_archives() for schema in archive.schemas)


def lookup_schema(*, archive: str, table: str) -> Schema | None:
    """Linear scan of the active schema KB. None if no curated entry.
    Matching is exact (case-sensitive) on both keys."""
    for s in active_schema_kb():
        if s.archive == archive and s.table == table:
            return s
    return None


def schema_to_dict(s: Schema) -> dict:
    """Serialize a Schema for inclusion in a tool's JSON envelope."""
    d = dataclass_to_jsonable_dict(s)
    d["notes"] = note_texts(s.notes)  # Notes -> LLM-facing text
    return d
