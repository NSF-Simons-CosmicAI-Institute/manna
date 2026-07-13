"""Compatibility view over the archive registry (`archives/`).

The canonical archive facts now live in per-archive modules under
`astro_archives_mcp/archives/` (one `archives/<short_name>.py` each, exporting
`ARCHIVE = Archive(...)`). This module is a thin view that preserves the
historical public surface:

- `Archive` — re-exported from `archives._model` (so existing imports work).
- `KNOWN_ARCHIVES` — the active archives, as a tuple, snapshotted at import.
- `active_archives()` — the same, resolved live from the active set.
- the derived lookups + endpoint-description helpers (unchanged behavior).

`KNOWN_ARCHIVES` and the endpoint helpers are import-time by nature (they feed
the label map in `_archive_label` and the `Field(examples=...)` in tool
schemas), so they reflect the deployment's selection as of process start —
which is when `STABLE_ARCHIVES` is read. Runtime tools that must honor a
mid-process re-selection (e.g. `vo_archive_list`) call `active_archives()`.

To add / remove an archive: add or delete a module under `archives/`, or set
`STABLE_ARCHIVES`. No other file needs touching. See docs/archives-spec.md.
"""

from astro_archives_mcp.archives import get_active_archives
from astro_archives_mcp.archives._model import Archive

__all__ = [
    "Archive",
    "KNOWN_ARCHIVES",
    "active_archives",
    "by_short_name",
    "host_substring_to_short_name",
    "scs_endpoint_description",
    "scs_endpoint_urls",
    "sia_endpoint_description",
    "sia_endpoint_urls",
    "tap_endpoint_description",
    "tap_endpoint_urls",
]


def active_archives() -> tuple[Archive, ...]:
    """The active archives (registry order), resolved live."""
    return get_active_archives()


# Snapshot at import — consumed by import-time machinery (label map, tool
# schema examples) and by tests. Equal to active_archives() at process start.
KNOWN_ARCHIVES: tuple[Archive, ...] = active_archives()


# ---------- derived lookups ----------


def by_short_name(name: str) -> Archive | None:
    """Return the archive with the given short_name, or None."""
    for a in KNOWN_ARCHIVES:
        if a.short_name == name:
            return a
    return None


def host_substring_to_short_name() -> dict[str, str]:
    """Flatten host_substrings tuple into a substring → short_name map.

    Used by `_archive_label._STATIC_MAP`. Archives with multiple
    host substrings (e.g. CADC's two) contribute multiple entries
    mapping to the same short_name.
    """
    return {
        sub: archive.short_name for archive in KNOWN_ARCHIVES for sub in archive.host_substrings
    }


def tap_endpoint_urls() -> list[str]:
    """All TAP URLs we know about, in registry order."""
    return [a.tap_url for a in KNOWN_ARCHIVES if a.tap_url]


def sia_endpoint_urls() -> list[str]:
    """All SIA URLs we know about, in registry order."""
    return [a.sia_url for a in KNOWN_ARCHIVES if a.sia_url]


def scs_endpoint_urls() -> list[str]:
    """All SCS URLs we know about, in registry order."""
    return [a.scs_url for a in KNOWN_ARCHIVES if a.scs_url]


# ---------- description helpers (used by tool Field descriptions) ----------


def _format_examples(archives: list[Archive], protocol: str) -> str:
    """Render a few example URLs inline for a tool's Field description.

    Used to keep the LLM-facing schema in sync with the canonical list
    without having to duplicate "'<url>' (<display_name>)" pairs by hand.
    """
    parts = []
    for a in archives:
        url = getattr(a, f"{protocol}_url")
        if url:
            parts.append(f"'{url}' ({a.display_name})")
    return " or ".join(parts)


def tap_endpoint_description() -> str:
    """The full description string for a TAP endpoint parameter."""
    primary = [a for a in KNOWN_ARCHIVES if a.tap_url][:2]
    return (
        f"Full TAP service URL. Example: {_format_examples(primary, 'tap')}. "
        "Discover other services via vo_registry_search."
    )


def sia_endpoint_description() -> str:
    """The full description string for a SIA endpoint parameter."""
    primary = [a for a in KNOWN_ARCHIVES if a.sia_url][:2]
    examples_text = _format_examples(primary, "sia")
    return (
        f"SIA endpoint URL — SIA 2.0 or 1.0. Example: {examples_text}. "
        "vo_sia_search auto-detects the version (SIA2, falling back to SIA1 "
        "as used by NOIRLab Data Lab); pass the version argument to force one. "
        "Discover endpoints with vo_registry_search(servicetype='sia')."
    )


def scs_endpoint_description() -> str:
    """The full description string for a SCS endpoint parameter."""
    primary = [a for a in KNOWN_ARCHIVES if a.scs_url][:2]
    return (
        f"Simple Cone Search endpoint URL. Example: {_format_examples(primary, 'scs')}. "
        "Prefer vo_tap_query for archives that expose a TAP endpoint — "
        "vo_cone_search is here for SCS-only legacy services."
    )
