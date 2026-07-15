"""Endpoint helpers over the active archive set.

Everything here resolves from ``get_active_archives()`` at call time. That
function is ``lru_cache``d, so the active set is process-frozen after first
use — there is no separate import-time snapshot to keep in sync (the old
``known_archives`` module-global snapshot / ``active_archives()`` duality is gone).
"""

from astro_archives_mcp.archives import get_active_archives
from astro_archives_mcp.archives._model import Archive

__all__ = [
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
    """The active archives (registry order)."""
    return get_active_archives()


def by_short_name(name: str) -> Archive | None:
    for a in active_archives():
        if a.short_name == name:
            return a
    return None


def host_substring_to_short_name() -> dict[str, str]:
    """Flatten host_substrings into a substring -> short_name map
    (consumed by `_archive_label._STATIC_MAP`)."""
    return {
        sub: archive.short_name for archive in active_archives() for sub in archive.host_substrings
    }


def tap_endpoint_urls() -> list[str]:
    return [a.tap_url for a in active_archives() if a.tap_url]


def sia_endpoint_urls() -> list[str]:
    return [a.sia_url for a in active_archives() if a.sia_url]


def scs_endpoint_urls() -> list[str]:
    return [a.scs_url for a in active_archives() if a.scs_url]


def _format_examples(archives: list[Archive], protocol: str) -> str:
    parts = []
    for a in archives:
        url = getattr(a, f"{protocol}_url")
        if url:
            parts.append(f"'{url}' ({a.display_name})")
    return " or ".join(parts)


def tap_endpoint_description() -> str:
    primary = [a for a in active_archives() if a.tap_url][:2]
    return (
        f"Full TAP service URL. Example: {_format_examples(primary, 'tap')}. "
        "Discover other services via vo_registry_search."
    )


def sia_endpoint_description() -> str:
    primary = [a for a in active_archives() if a.sia_url][:2]
    return (
        f"SIA endpoint URL — SIA 2.0 or 1.0. Example: {_format_examples(primary, 'sia')}. "
        "vo_sia_search auto-detects the version (SIA2, falling back to SIA1 "
        "as used by NOIRLab Data Lab); pass the version argument to force one. "
        "Discover endpoints with vo_registry_search(servicetype='sia')."
    )


def scs_endpoint_description() -> str:
    primary = [a for a in active_archives() if a.scs_url][:2]
    return (
        f"Simple Cone Search endpoint URL. Example: {_format_examples(primary, 'scs')}. "
        "Prefer vo_tap_query for archives that expose a TAP endpoint — "
        "vo_cone_search is here for SCS-only legacy services."
    )
