"""Trap delivery — derive the push channels from the active archive set.

Two channels, both fed by `Note.trap` (see `_model.Trap` for the taxonomy):

- `silent_trap_cheatsheet()` — a compact preventive blob appended to the
  `vo_tap_query` description at `build_mcp()` time. This is the token-expensive
  channel: the description is re-sent on every turn, so it is deliberately
  capped (`CHEATSHEET_TOKEN_BUDGET`) and carries `guidance` only, never the
  note's full prose. `vo_archive_list` remains the place for everything else.
- `loud_trap_guidance()` — looked up at failure time, attached to the error
  payload's `hint`. Costs nothing until a query actually trips it.

Everything resolves from `get_active_archives()` at call time, so `STABLE_ARCHIVES`
selection is honoured for free and there is no import-time snapshot to keep in
sync — same contract as `_endpoints.py`.
"""

from urllib.parse import urlparse

from astro_archives_mcp.archives._endpoints import active_archives, by_short_name
from astro_archives_mcp.archives._model import Archive, Note

__all__ = [
    "CHEATSHEET_HEADER",
    "CHEATSHEET_TOKEN_BUDGET",
    "estimate_tokens",
    "loud_trap_guidance",
    "silent_trap_cheatsheet",
    "trap_notes",
]

# The description is re-sent every turn, so the cheatsheet is rent we pay
# continuously. 200 tokens is the ceiling agreed in issue #57 — if a new silent
# trap won't fit, the fix is a terser `guidance`, not a bigger budget.
CHEATSHEET_TOKEN_BUDGET = 200

# Public because it is the seam the eval's ablation arm cuts on: the harness's
# strip_cheatsheet removes the blob to measure what injecting it is worth.
CHEATSHEET_HEADER = (
    "Archive quirks that give wrong results or unactionable errors — apply BEFORE querying:"
)


def estimate_tokens(text: str) -> int:
    """Rough token count (~4 chars/token). Good enough to guard a budget; we are
    checking for a blown ceiling, not billing anyone."""
    return len(text) // 4


def trap_notes(archive: Archive, *, loud: bool) -> list[Note]:
    """The archive's loud (or silent) trap notes, in declaration order.

    Covers usage_notes and per-table schema notes — a trap is worth pushing
    wherever it was curated.
    """
    notes = list(archive.usage_notes)
    for schema in archive.schemas:
        notes.extend(schema.notes)
    return [n for n in notes if n.trap is not None and n.trap.is_loud == loud]


def _cheatsheet_key(archive: Archive) -> str:
    """What the model should match its `endpoint` argument against.

    The TAP host, not `host_substrings[0]` — this blob rides vo_tap_query, and
    for NRAO those disagree ('data.nrao' never appears in the TAP endpoint
    'data-query.nrao.edu'), which would send the model looking for the wrong
    archive's advice.
    """
    host = urlparse(archive.tap_url).hostname if archive.tap_url else None
    return host or archive.short_name


def _cheatsheet_line(archive: Archive, note: Note) -> str:
    assert note.trap is not None  # guaranteed by trap_notes
    return f"- {archive.display_name} ({_cheatsheet_key(archive)}): {note.trap.guidance}"


def silent_trap_cheatsheet() -> str:
    """The preventive blob for the vo_tap_query description, or "" if no active
    archive tags a silent trap (e.g. a STABLE_ARCHIVES set that excludes them).

    Ordered by archive priority, so the archives we steer toward lead.
    """
    lines = [
        _cheatsheet_line(a, n)
        for a in sorted(active_archives(), key=lambda a: (a.priority, a.short_name))
        for n in trap_notes(a, loud=False)
    ]
    if not lines:
        return ""
    return "\n".join([CHEATSHEET_HEADER, *lines])


def loud_trap_guidance(archive_short_name: str, adql: str) -> str | None:
    """Guidance for the first loud trap `adql` trips at this archive, else None.

    `archive_short_name` comes from `archive_label(endpoint)`; an unknown or
    unselected archive simply has no curated claims, so this returns None and
    the error payload is unchanged.
    """
    archive = by_short_name(archive_short_name)
    if archive is None:
        return None
    for note in trap_notes(archive, loud=True):
        assert note.trap is not None  # guaranteed by trap_notes
        if note.trap.fires_on(adql):
            return note.trap.guidance
    return None
