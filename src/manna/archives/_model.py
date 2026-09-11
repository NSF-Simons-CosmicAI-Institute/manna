"""Archive model — the dataclasses one archive's knowledge is built from.

An **archive** is the portable, plugin-style unit of archive notes: its
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

from manna.archives._audit import Audit
from manna.archives._count import CountTarget


@dataclass(frozen=True)
class Pitfall:
    """A pitfall: how a note's claim gets DELIVERED to the model, and when.

    A note in `list_archives` is knowledge the model *can* reach. A pitfall is
    knowledge we push at it, because the eval showed reachable isn't enough
    (issue #57: the NRAO LOWER/UPPER note was true, probed, and served — and
    the model still wrote LOWER()). Like `Audit`, this is declarative: it
    carries no delivery code. `archives/_pitfalls.py` reads these.

    Two kinds, split by whether the model can self-correct from the failure,
    and told apart entirely by ``triggers``:

    - **up-front note** (no ``triggers``; called *silent* in the code) — the
      model gets NO usable correction
      signal, so the claim must arrive BEFORE the query. Either the query
      silently returns a wrong answer (ALMA: COUNT(*) over-counts, no error)
      or it errors so cryptically that the message doesn't imply the fix
      (Data Lab: ADQL geometry surfaces as `function point(...) does not
      exist`, which never suggests q3c). These go in the `run_adql_query`
      description — the expensive channel, re-sent every turn, so the bar is
      high and `guidance` must be terse.
    - **error hint** (``triggers`` set; called *loud* in the code) — the query
      throws, and the triggers
      recognise the cause in the submitted ADQL. `guidance` rides the error
      payload's `hint` instead, so it costs nothing until it fires.

    `guidance` is the compact, imperative fix — not the note's full prose.
    """

    guidance: str
    # Case-insensitive substrings of the submitted ADQL that fire an error hint.
    # Empty ⇒ up-front note (preventive, always shown); non-empty ⇒ error hint
    # (reactive). `channel` is the only reader of this distinction.
    triggers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.guidance:
            raise ValueError("Pitfall.guidance must be non-empty")

    @property
    def channel(self) -> Literal["upfront", "error_hint"]:
        """Up-front notes have no triggers and ride the tool description;
        error hints have triggers and ride the failure payload's `hint`."""
        return "error_hint" if self.triggers else "upfront"

    def fires_on(self, adql: str) -> bool:
        """Whether `adql` hits this pitfall. Up-front notes never fire (no triggers)."""
        low = adql.lower()
        return any(t.lower() in low for t in self.triggers)


@dataclass(frozen=True)
class Note:
    """One ATOMIC curated claim + the audit that re-checks it live.

    `id` is a stable slug, unique within its owning archive — the address a
    stale audit prints so you can jump straight to the note to fix. `text` is
    the single-claim, LLM-facing prose surfaced by list_archives /
    describe_table. `audit` (mandatory) is how the live runner re-checks it.
    `pitfall` (optional) opts the claim into a push channel — see `Pitfall`.
    """

    id: str
    text: str
    audit: Audit
    pitfall: Pitfall | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Note.id must be a non-empty slug")
        if not self.text:
            raise ValueError("Note.text must be non-empty")
        if not isinstance(self.audit, Audit):
            raise TypeError(f"Note.audit must be an Audit, got {type(self.audit).__name__}")
        if self.pitfall is not None and not isinstance(self.pitfall, Pitfall):
            raise TypeError(f"Note.pitfall must be a Pitfall, got {type(self.pitfall).__name__}")


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
    """Archive notes about ONE table at one archive.

    `archive` is the owning archive's short_name. It is redundant with the
    owning `Archive.short_name` (validated in `Archive.__post_init__`) but kept
    because it is part of the `describe_table` response contract and lets
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
      quirks, target-name conventions). Surfaced via `list_archives`.
    - `schemas` — curated per-table `Schema` facts for this archive. Surfaced
      via `describe_table`; not echoed by `list_archives`.
    - `count_target` — optional CountTarget: how to build a positional COUNT
      for this archive's primary table (used by count_observations_near_target /
      survey_archives_for_target). None ⇒ not directly countable (still reachable via
      the atomic tools).
    - `priority` — ascending sort key (ties broken by short_name). The explicit
      replacement for the old "declaration order is load-bearing" convention:
      the first TAP-having archives become the endpoint examples shown to the
      LLM, so lower numbers are the archives we steer toward.

    An archive is discovered by the registry (see `archives/__init__.py`) as
    the module-level `ARCHIVE` in an `archives/<short_name>.py` file. Dropping
    the file (or excluding it via `MANNA_ARCHIVES`) removes the server's
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
    count_target: CountTarget | None = None
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
