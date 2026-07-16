"""Archive model — the dataclasses one archive's knowledge is built from.

An **archive** is the portable, plugin-style unit of curated knowledge: its
identity + endpoints + usage_notes, together with the per-table `Schema`
entries for that same archive. One archive = one file under `archives/`.

`Archive` and `Schema` live here so the model is a dependency-free leaf; the
endpoint/schema helpers in `archives/_endpoints.py` and `archives/_knowledge.py`
import them from here. `Note` (one atomic curated claim) and its `Audit` (how
the live runner re-checks it) also
live here — every `usage_notes` / `Schema.notes` entry is a `Note`, no other
form accepted.
"""

from dataclasses import dataclass, field
from typing import Literal

from astro_archives_mcp.archives._audit import Audit

TRAP_KINDS: frozenset[str] = frozenset({"silent", "loud"})


@dataclass(frozen=True)
class Trap:
    """How a note's claim gets DELIVERED to the model, and when.

    A note in `vo_archive_list` is knowledge the model *can* reach. A trap is
    knowledge we push at it, because the eval showed reachable isn't enough
    (issue #57: the NRAO LOWER/UPPER note was true, probed, and served — and
    the model still wrote LOWER()). Like `Audit`, this is declarative: it
    carries no delivery code. `archives/_traps.py` reads these.

    Two kinds, split by whether the model can self-correct from the failure:

    - ``silent`` — the model gets NO usable correction signal, so the claim
      must arrive BEFORE the query. Either the query silently returns a wrong
      answer (ALMA: COUNT(*) over-counts, no error) or it errors so cryptically
      that the message doesn't imply the fix (Data Lab: ADQL geometry surfaces
      as `function point(...) does not exist`, which never suggests q3c). These
      go in the `vo_tap_query` description — the expensive channel, re-sent
      every turn, so the bar is high and `guidance` must be terse.
    - ``loud`` — the query throws, and we can recognise the cause from the
      submitted ADQL. `guidance` rides the error payload's `hint` instead, so
      it costs nothing until it fires. Needs `triggers`.

    `guidance` is the compact, imperative fix — not the note's full prose.
    """

    kind: Literal["silent", "loud"]
    guidance: str
    # Case-insensitive substrings of the submitted ADQL that fire a loud trap.
    triggers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in TRAP_KINDS:
            raise ValueError(f"unknown trap kind {self.kind!r}; one of {sorted(TRAP_KINDS)}")
        if not self.guidance:
            raise ValueError("Trap.guidance must be non-empty")
        if self.kind == "loud" and not self.triggers:
            raise ValueError("a loud trap needs triggers — they decide when the hint fires")
        if self.kind == "silent" and self.triggers:
            raise ValueError(
                "a silent trap must not carry triggers: it is preventive and always shown, "
                "so there is nothing to match against"
            )

    def fires_on(self, adql: str) -> bool:
        """Whether `adql` trips this trap. Silent traps never fire (no triggers)."""
        low = adql.lower()
        return any(t.lower() in low for t in self.triggers)


@dataclass(frozen=True)
class Note:
    """One ATOMIC curated claim + the audit that re-checks it live.

    `id` is a stable slug, unique within its owning archive — the address a
    stale audit prints so you can jump straight to the note to fix. `text` is
    the single-claim, LLM-facing prose surfaced by vo_archive_list /
    vo_schema_describe. `audit` (mandatory) is how the live runner re-checks it.
    `trap` (optional) opts the claim into a push channel — see `Trap`.
    """

    id: str
    text: str
    audit: Audit
    trap: Trap | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Note.id must be a non-empty slug")
        if not self.text:
            raise ValueError("Note.text must be non-empty")
        if not isinstance(self.audit, Audit):
            raise TypeError(f"Note.audit must be an Audit, got {type(self.audit).__name__}")
        if self.trap is not None and not isinstance(self.trap, Trap):
            raise TypeError(f"Note.trap must be a Trap, got {type(self.trap).__name__}")


def note_texts(notes: tuple[Note, ...]) -> list[str]:
    """The LLM-facing strings for a tuple of notes, in order. Audit stays internal."""
    return [n.text for n in notes]


def _normalize_notes(notes) -> tuple[Note, ...]:
    """Every note must be an explicit Note (the coverage invariant is total)."""
    for n in notes:
        if not isinstance(n, Note):
            raise TypeError(f"note must be a Note, got {type(n).__name__}")
    return tuple(notes)


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
    notes: tuple[Note, ...] = ()
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
    usage_notes: tuple[Note, ...] = field(default_factory=tuple)
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
