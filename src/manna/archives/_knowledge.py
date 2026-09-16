"""Per-table archive notes (Schema entries) over the active archive set."""

from manna._serialization import dataclass_to_jsonable_dict
from manna.archives import get_active_archives
from manna.archives._model import Schema, note_texts

__all__ = ["active_schemas", "lookup_schema", "schema_to_dict"]


def active_schemas() -> tuple[Schema, ...]:
    """Every active archive's schemas, flattened in registry order."""
    return tuple(schema for archive in get_active_archives() for schema in archive.schemas)


def lookup_schema(*, archive: str, table: str) -> Schema | None:
    """Linear scan of the active archive notes' schemas. None if no curated entry.
    Matching is exact (case-sensitive) on both keys."""
    for s in active_schemas():
        if s.archive == archive and s.table == table:
            return s
    return None


def schema_to_dict(s: Schema) -> dict:
    """Serialize a Schema for inclusion in a tool's JSON envelope.

    `cross_refs` is narrowed to archives in the active set: a reference to a
    paused or deselected archive would send the model to a `describe_table`
    call that answers `known: false`. The dataclass keeps the full tuple.
    """
    d = dataclass_to_jsonable_dict(s)
    d["notes"] = note_texts(s.notes)  # Notes -> LLM-facing text
    active = {a.short_name for a in get_active_archives()}
    d["cross_refs"] = [[archive, table] for archive, table in s.cross_refs if archive in active]
    return d
