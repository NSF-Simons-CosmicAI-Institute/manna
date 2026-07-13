"""Archive model — the dataclasses one archive's knowledge is built from.

An **archive** is the portable, plugin-style unit of curated knowledge: its
identity + endpoints + usage_notes, together with the per-table `Schema`
entries for that same archive. One archive = one file under `archives/`.

`Archive` and `Schema` live here (not in `known_archives` / `schema_kb`) so the
model is a dependency-free leaf. Those old modules re-export both for backward
compatibility, so `from astro_archives_mcp.known_archives import Archive` and
`from astro_archives_mcp.schema_kb import Schema` keep working.
"""

from dataclasses import dataclass, field

from astro_archives_mcp.archives._audit import Audit


@dataclass(frozen=True)
class Note:
    """One ATOMIC curated claim + the audit that re-checks it live.

    `id` is a stable slug, unique within its owning archive — the address a
    stale audit prints so you can jump straight to the note to fix. `text` is
    the single-claim, LLM-facing prose surfaced by vo_archive_list /
    vo_schema_describe. `audit` (mandatory) is how the live runner re-checks it.
    """

    id: str
    text: str
    audit: Audit

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Note.id must be a non-empty slug")
        if not self.text:
            raise ValueError("Note.text must be non-empty")
        if not isinstance(self.audit, Audit):
            raise TypeError(f"Note.audit must be an Audit, got {type(self.audit).__name__}")


def note_texts(notes: tuple[Note, ...]) -> list[str]:
    """The LLM-facing strings for a tuple of notes, in order. Audit stays internal."""
    return [n.text for n in notes]


# MIGRATION SCAFFOLD: the type an un-migrated archive is still allowed to pass
# for usage_notes/notes at construction time. `_normalize_notes` coerces every
# element to a `Note` in `__post_init__`, so the field holds `tuple[Note, ...]`
# for the object's entire post-construction lifetime — callers (note_texts,
# vo_archive_list, vo_schema_describe) may treat it as Note-only. Task 8 wraps
# every archive's bare strings in explicit `Note(...)`s and removes this alias
# (and the str branch in `_normalize_notes` below).
NoteInput = Note | str


def _normalize_notes(notes) -> tuple[Note, ...]:
    """Coerce a notes tuple to Notes.

    MIGRATION SCAFFOLD: a bare `str` is wrapped as a manual, un-audited note so
    an un-migrated archive still constructs and the tree stays green. Task 8
    removes the str branch, making explicit `Note`s mandatory.
    """
    out: list[Note] = []
    for i, n in enumerate(notes):
        if isinstance(n, Note):
            out.append(n)
        elif isinstance(n, str):
            out.append(
                Note(id=f"_auto{i}", text=n, audit=Audit.manual("unmigrated note — pending audit"))
            )
        else:
            raise TypeError(f"note must be a Note or str, got {type(n).__name__}")
    return tuple(out)


@dataclass(frozen=True)
class Schema:
    """Curated knowledge about ONE table at one archive.

    `archive` is the owning archive's short_name. It is redundant with the
    owning `Archive.short_name` (validated in `Archive.__post_init__`) but kept
    because it is part of the `vo_schema_describe` response contract and lets
    `cross_refs` name tables as `(archive, table)` pairs.
    """

    archive: str
    table: str

    missing_standard_columns: tuple[str, ...] = ()
    value_enums: dict[str, tuple[str, ...]] = field(default_factory=dict)
    notes: tuple[NoteInput, ...] = ()
    # 2-tuple form, not "archive:table" strings, to avoid parsing fragility.
    cross_refs: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "notes", _normalize_notes(self.notes))


@dataclass(frozen=True)
class Archive:
    """Everything the server knows about ONE IVOA archive, in one place.

    Identity + best-effort endpoints (`tap_url` / `sia_url` / `scs_url` are
    None when the archive doesn't expose one we surface), plus:

    - `usage_notes` — short agent-facing strings capturing archive-specific
      gotchas (non-standard table locations, sync-vs-async routing, ADQL
      quirks, target-name conventions). Surfaced via `vo_archive_list`.
    - `schemas` — curated per-table `Schema` facts for this archive. Surfaced
      via `vo_schema_describe`; not echoed by `vo_archive_list`.
    - `priority` — ascending sort key (ties broken by short_name). The explicit
      replacement for the old "declaration order is load-bearing" convention:
      the first TAP-having archives become the endpoint examples shown to the
      LLM, so lower numbers are the archives we steer toward.

    An archive is discovered by the registry (see `archives/__init__.py`) as
    the module-level `ARCHIVE` in an `archives/<short_name>.py` file. Dropping
    the file (or excluding it via `STABLE_ARCHIVES`) removes the server's
    *claims* about that archive — never its reachability. See
    docs/archives-spec.md.
    """

    short_name: str
    display_name: str
    host_substrings: tuple[str, ...]
    tap_url: str | None = None
    sia_url: str | None = None
    scs_url: str | None = None
    waveband: str | None = None
    description: str = ""
    notable_tables: tuple[str, ...] = field(default_factory=tuple)
    usage_notes: tuple[NoteInput, ...] = field(default_factory=tuple)
    schemas: tuple[Schema, ...] = field(default_factory=tuple)
    priority: int = 100

    def __post_init__(self) -> None:
        object.__setattr__(self, "usage_notes", _normalize_notes(self.usage_notes))
        # Every schema must belong to this archive. Enforced at construction so
        # a hand-built archive — in a test or any non-discovery caller — can't
        # drift either.
        for schema in self.schemas:
            if schema.archive != self.short_name:
                raise ValueError(
                    f"Archive {self.short_name!r} owns a Schema declared for "
                    f"archive={schema.archive!r} (table={schema.table!r}); the "
                    f"schema.archive must match the archive's short_name."
                )
