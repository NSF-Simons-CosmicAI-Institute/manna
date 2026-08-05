"""Archive-label lookup — fast, deterministic, no network.

Two-step resolution:
  1. Static substring map derived from the active archive set
     (`archives._endpoints.host_substring_to_short_name`; no I/O, fast path)
  2. Hostname-derived label for everything else (e.g. 'archive.eso.org'
     -> 'eso')

The label is a cosmetic field on response envelopes (`archive`). It does
NOT hit the IVOA registry: an earlier version fell back to a RegTAP scan
of every registered TAP service just to read one `short_name`, which
added multi-second latency to the first query against any unregistered
endpoint. A hostname-derived label is good enough for a display string
and costs nothing.

There is deliberately NO memoization here. An earlier version kept a
process-global `dict` keyed by the full endpoint URL — i.e. keyed by a tool
argument, unbounded, never evicted, in a server every tenant shares. One
caller could grow it without limit (`vo_tap_abort` swallows upstream errors
and still labels its response, so every call was a guaranteed write), and
measured at ~141 bytes/entry that is a slow memory leak with an attacker
holding the tap. It was removed rather than capped because it saved ~0.01us
per call on a code path whose callers spend 10ms-1s on network I/O — the
whole function is a substring scan over ~10 needles plus a `urlparse`.

To add an archive to the static map, add a module under `archives/` (its
`host_substrings` flow into the map via `host_substring_to_short_name`);
`archive_label` picks it up automatically.
"""

from urllib.parse import urlparse

from manna.archives._endpoints import host_substring_to_short_name

# (substring → short_name). Substring matched lowercase against the full URL.
# Derived once at import from the active archive set; do not edit directly.
_STATIC_MAP: dict[str, str] = host_substring_to_short_name()

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
    """Resolve an endpoint URL to a short archive label (no network, no state)."""
    low = endpoint.lower()
    for needle, label in _STATIC_MAP.items():
        if needle in low:
            return label

    host = urlparse(endpoint).hostname or ""
    return _label_from_host(host) or "other"


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
