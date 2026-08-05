"""Shared resolve + archive-selection helpers for the purpose-built facades.

`vo_find_observations`, `vo_count_observations`, and `vo_survey_target` all
resolve a target to coordinates and pick an archive by a capability attribute
(`sia_url` / `scs_url` / `count_target`), filtered by waveband or an explicit
override. Those pure pieces live here so no facade imports another.
"""

from manna.archives._endpoints import active_archives
from manna.archives._model import Archive
from manna.backends.resolver import ResolverClient

_resolver: ResolverClient | None = None


def get_resolver() -> ResolverClient:
    global _resolver
    if _resolver is None:
        _resolver = ResolverClient()
    return _resolver


def coerce_or_resolve(target: str) -> tuple[float | None, float | None]:
    """`'187.7 12.4'` / `'187.7, 12.4'` -> parsed floats; else Sesame-resolve.

    Returns `(None, None)` on a resolver miss so callers can soft-fail. A
    two-token all-float string is treated as literal ICRS coords (object names
    never parse as two floats), so the resolver is never called for them.
    """
    tokens = target.replace(",", " ").split()
    if len(tokens) == 2:
        try:
            return float(tokens[0]), float(tokens[1])
        except ValueError:
            pass
    hit = get_resolver().resolve(target)
    return hit if hit is not None else (None, None)


def rank_by_attr(*, attr: str, waveband: str | None, override: str | None) -> list[Archive]:
    """Active archives whose `attr` is truthy, filtered by waveband/override,
    ordered by (priority, short_name). `active_archives()` is already sorted
    that way, but we sort explicitly here too so callers that monkeypatch it
    with an unsorted fixture still get a deterministic, priority-first order."""
    candidates = sorted(
        (a for a in active_archives() if getattr(a, attr)),
        key=lambda a: (a.priority, a.short_name),
    )
    if override is not None:
        ov = override.strip().lower()
        candidates = [a for a in candidates if a.short_name.lower() == ov]
    if waveband is not None:
        wb = waveband.strip().lower()
        candidates = [a for a in candidates if (a.waveband or "").lower() == wb]
    return candidates


def no_candidate_payload(
    *,
    attr: str,
    service_label: str,
    waveband: str | None,
    override: str | None,
    servicetype: str | None = None,
) -> dict:
    """Recovery hint when no active archive matches — never a hard failure."""
    capable = [a for a in active_archives() if getattr(a, attr)]
    known = ", ".join(f"{a.short_name} ({a.waveband})" for a in capable) or "none"
    filt = []
    if waveband is not None:
        filt.append(f"waveband={waveband!r}")
    if override is not None:
        filt.append(f"archive={override!r}")
    filt_text = " and ".join(filt) if filt else "the given filter"
    registry_hint = (
        f"vo_registry_search(servicetype={servicetype!r})" if servicetype else "vo_registry_search"
    )
    return {
        "count": 0,
        "hint": (
            f"No known archive offers {service_label} matching {filt_text}. "
            f"Archives that do: {known}. Relax the filter, pass an explicit "
            f"`archive`, or discover more via {registry_hint}."
        ),
    }
