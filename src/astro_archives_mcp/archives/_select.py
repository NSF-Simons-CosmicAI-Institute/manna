"""Pure archive selection, ordering, and validation.

No environment reads, no imports of the archive modules — every function takes
its inputs explicitly, so filtering is unit-testable without reloading the
package. The imperative shell that reads `Settings` and imports archive modules
lives in `archives/__init__.py`.
"""

import logging

from astro_archives_mcp.archives._model import Archive

logger = logging.getLogger(__name__)


def parse_allow(raw: str | None) -> frozenset[str] | None:
    """Parse a `STABLE_ARCHIVES` value into a lower-cased allow-set.

    Returns None (meaning "all archives active") for an unset or empty/
    whitespace-only value, so the default deployment ships every archive.
    """
    if raw is None:
        return None
    names = frozenset(part.strip().lower() for part in raw.split(",") if part.strip())
    return names or None


def sort_archives(archives: tuple[Archive, ...]) -> tuple[Archive, ...]:
    """Order by (priority ascending, short_name) — total & deterministic."""
    return tuple(sorted(archives, key=lambda a: (a.priority, a.short_name)))


def select_archives(
    archives: tuple[Archive, ...],
    *,
    allow: frozenset[str] | None,
) -> tuple[Archive, ...]:
    """Filter `archives` to the allow-set, sorted. `allow=None` => all.

    Unknown names in `allow` are logged and ignored — a config typo must
    never crash the server. An empty result is allowed (logged as a
    warning); the server still boots and stays useful via registry discovery.
    """
    if allow is None:
        return sort_archives(archives)

    known = {a.short_name.lower() for a in archives}
    unknown = allow - known
    if unknown:
        logger.warning(
            "STABLE_ARCHIVES names unknown archive(s) %s; ignoring. Known: %s",
            sorted(unknown),
            sorted(known),
        )

    selected = sort_archives(tuple(a for a in archives if a.short_name.lower() in allow))
    if not selected:
        logger.warning(
            "STABLE_ARCHIVES selected no archives (allow=%s). The server will "
            "make no curated claims; archives remain reachable via "
            "vo_registry_search.",
            sorted(allow),
        )
    return selected


def validate_archives(archives: tuple[Archive, ...]) -> None:
    """Cross-archive integrity checks. Raises ValueError on a developer error.

    Enforced:
      - short_names are unique across archives,
      - (archive, table) pairs are unique across all archives.

    Per-archive invariants (a schema belongs to its owning archive) are
    enforced by `Archive.__post_init__`, so an archive is well-formed the
    moment it is built — not just when it passes through here.

    NOT enforced here: that `cross_refs` resolve. A subset deployment
    legitimately drops the referenced archive, so a dangling cross_ref is
    tolerated at runtime. The full-set-resolves invariant is a test.
    """
    short_names = [a.short_name for a in archives]
    dupes = {n for n in short_names if short_names.count(n) > 1}
    if dupes:
        raise ValueError(f"Duplicate archive short_name(s): {sorted(dupes)}")

    seen_tables: set[tuple[str, str]] = set()
    for archive in archives:
        for schema in archive.schemas:
            key = (schema.archive, schema.table)
            if key in seen_tables:
                raise ValueError(f"Duplicate Schema entry for {key}; collapse the duplicates")
            seen_tables.add(key)
