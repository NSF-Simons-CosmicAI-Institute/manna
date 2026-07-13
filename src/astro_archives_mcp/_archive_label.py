"""Archive-label lookup — fast, deterministic, no network.

Two-step resolution:
  1. Static substring map derived from `known_archives.KNOWN_ARCHIVES`
     (the curated short_names; no I/O, fast path)
  2. Hostname-derived label for everything else (e.g. 'archive.eso.org'
     -> 'eso'), memoized in a process-lifetime cache

The label is a cosmetic field on response envelopes (`archive`). It does
NOT hit the IVOA registry: an earlier version fell back to a RegTAP scan
of every registered TAP service just to read one `short_name`, which
added multi-second latency to the first query against any unregistered
endpoint. A hostname-derived label is good enough for a display string
and costs nothing.

Cache is keyed by the full endpoint URL (not just hostname) so distinct
services on the same host get distinct labels. Restart wipes it; the
derivation is deterministic, so a stale entry is never wrong.

To add an archive to the static map, add a module under `archives/` (its
`host_substrings` flow into `KNOWN_ARCHIVES` via the compat view). Both
`archive_label` and `is_known_archive_url` pick it up automatically.

Note: `is_known_archive_url` is vestigial — its only caller (`vo_sia_fetch`)
was removed in the 0.4.0 stateless refactor. It is retained (and tested) for
now; a follow-up may drop it.
"""

from urllib.parse import urlparse

from astro_archives_mcp.known_archives import host_substring_to_short_name

# (substring → short_name). Substring matched lowercase against the full URL.
# Derived once at import from KNOWN_ARCHIVES; do not edit directly.
_STATIC_MAP: dict[str, str] = host_substring_to_short_name()

_CACHE: dict[str, str] = {}

# Minimal set of multi-label public suffixes seen across astronomy / academic
# hosts. Not a full public-suffix list — just enough that the derived label
# lands on the institution (e.g. 'nao.ac.jp' -> the label before 'ac.jp')
# rather than a country/sector code.
_MULTI_LABEL_SUFFIXES: frozenset[str] = frozenset(
    {
        "ac.jp",
        "ac.uk",
        "ac.za",
        "ac.nz",
        "ac.kr",
        "ac.at",
        "ac.be",
        "co.uk",
        "co.jp",
        "co.nz",
        "co.za",
        "edu.au",
        "gov.au",
        "org.au",
        "gc.ca",
    }
)


def archive_label(endpoint: str) -> str:
    """Resolve an endpoint URL to a short archive label (no network)."""
    # Cache first: an O(1) hit skips the static-map scan on repeat calls to
    # the same endpoint (the common case across a multi-turn session). Only
    # non-static URLs are ever cached — static hits return before the write.
    if endpoint in _CACHE:
        return _CACHE[endpoint]

    low = endpoint.lower()
    for needle, label in _STATIC_MAP.items():
        if needle in low:
            return label

    host = urlparse(endpoint).hostname or ""
    label = _label_from_host(host) or "other"
    _CACHE[endpoint] = label
    return label


def _label_from_host(host: str) -> str | None:
    """Best-effort short label from a hostname. None if nothing usable.

    Returns the registrable domain's principal label:
    'archive.eso.org' -> 'eso', 'mast.stsci.edu' -> 'stsci',
    'gea.esac.esa.int' -> 'esa'.
    """
    host = host.strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    labels = [p for p in host.split(".") if p]
    if not labels:
        return None
    if len(labels) <= 2:
        return labels[0]
    if ".".join(labels[-2:]) in _MULTI_LABEL_SUFFIXES:
        return labels[-3]
    return labels[-2]


def is_known_archive_url(url: str) -> bool:
    """Return True iff the URL host substring-matches an entry in
    `_STATIC_MAP`.

    SSRF allow-list helper: validates that a URL points at a known IVOA
    archive rather than an arbitrary host. The function deliberately does
    NOT consult the cache (`_CACHE`); a hostname-derived cache entry must
    never widen the allow-list.
    """
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except (ValueError, TypeError):
        return False
    if not host:
        return False
    for needle in _STATIC_MAP:
        if needle in host:
            return True
    return False
