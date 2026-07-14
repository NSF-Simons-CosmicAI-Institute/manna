"""Purpose-driven orchestration tool: vo_find_observations.

The atomic ``vo_*`` tools each expose one IVOA primitive (resolve a name,
list archives, run a SIA / cone search). Answering a real astronomer question
— *"give me images of M87 in the radio"* — means chaining three of them, and
the model has to do that planning itself.

``vo_find_observations`` collapses that chain into one call. It is a thin
FACADE over the SAME backends the atomic tools use:

    target ──(vo_target_resolve)──▶ ra/dec
           ──(vo_archive_list)────▶ pick an archive by service + waveband
           ──(vo_sia_search /
              vo_cone_search)─────▶ shaped inline envelope

Nothing is hidden: the response carries a ``resolved`` block (what coordinates
were used) and a ``plan`` block (which archive was chosen, its endpoint, the
alternatives, and its usage_notes) so the model can drop down to the atomic
tools whenever it wants a different archive or finer control. Selection is
additive, never gating — an unmatched filter returns a recovery hint naming
the archives that *do* offer the requested service, never a hard failure.
"""

from typing import Annotated, Literal

from pydantic import Field

from astro_archives_mcp.archives._model import note_texts
from astro_archives_mcp.backends.cone import ConeSearchClient
from astro_archives_mcp.backends.resolver import ResolverClient
from astro_archives_mcp.backends.sia import SiaClient
from astro_archives_mcp.errors import ValidationError, wrap_tool_errors
from astro_archives_mcp.known_archives import active_archives
from astro_archives_mcp.shaper import shape_table
from astro_archives_mcp.tools._constants import _ERROR_DOCSTRING

_resolver: ResolverClient | None = None
_sia: SiaClient | None = None
_cone: ConeSearchClient | None = None


def _get_resolver() -> ResolverClient:
    """Lazy accessor so tests can patch the resolver without import-time I/O."""
    global _resolver
    if _resolver is None:
        _resolver = ResolverClient()
    return _resolver


def _get_sia() -> SiaClient:
    """Lazy accessor so tests can patch the SIA backend."""
    global _sia
    if _sia is None:
        _sia = SiaClient()
    return _sia


def _get_cone() -> ConeSearchClient:
    """Lazy accessor so tests can patch the cone backend."""
    global _cone
    if _cone is None:
        _cone = ConeSearchClient()
    return _cone


def _coerce_or_resolve(target: str) -> tuple[float | None, float | None]:
    """``'187.7 12.4'`` / ``'187.7, 12.4'`` -> parsed floats; else Sesame-resolve.

    Returns ``(None, None)`` on a resolver miss so the caller can soft-fail.
    A two-token all-float string is treated as literal ICRS coordinates and
    the resolver is never called (object names never parse as two floats).
    """
    tokens = target.replace(",", " ").split()
    if len(tokens) == 2:
        try:
            return float(tokens[0]), float(tokens[1])
        except ValueError:
            pass
    hit = _get_resolver().resolve(target)
    return hit if hit is not None else (None, None)


def _rank_candidates(*, service: str, waveband: str | None, override: str | None):
    """Active archives that offer ``service``, filtered by waveband / override.

    Returns them in registry order (already sorted by ``(priority, short_name)``),
    so element 0 is the archive we steer toward.
    """
    url_attr = "sia_url" if service == "image" else "scs_url"
    candidates = [a for a in active_archives() if getattr(a, url_attr)]
    if override is not None:
        ov = override.strip().lower()
        candidates = [a for a in candidates if a.short_name.lower() == ov]
    if waveband is not None:
        wb = waveband.strip().lower()
        candidates = [a for a in candidates if (a.waveband or "").lower() == wb]
    return candidates


def _no_candidate_payload(*, service: str, waveband: str | None, override: str | None) -> dict:
    """Recovery hint when no active archive matches — never a hard failure."""
    url_attr = "sia_url" if service == "image" else "scs_url"
    servicetype = "sia" if service == "image" else "scs"
    capable = [a for a in active_archives() if getattr(a, url_attr)]
    known = ", ".join(f"{a.short_name} ({a.waveband})" for a in capable) or "none"
    filt = []
    if waveband is not None:
        filt.append(f"waveband={waveband!r}")
    if override is not None:
        filt.append(f"archive={override!r}")
    filt_text = " and ".join(filt) if filt else "the given filter"
    return {
        "count": 0,
        "hint": (
            f"No known archive offers a {service} service matching {filt_text}. "
            f"Archives with a {service} endpoint: {known}. Relax the filter, pass an "
            f"explicit `archive`, or discover more via "
            f"vo_registry_search(servicetype='{servicetype}')."
        ),
    }


@wrap_tool_errors
def vo_find_observations(
    target: Annotated[
        str,
        Field(
            description=(
                "Object name (resolved via CDS Sesame — 'M87', 'Cygnus A', "
                "'3C 273') OR explicit ICRS coordinates as 'RA DEC' in decimal "
                "degrees ('187.7059 12.3911', comma optional). Names are "
                "auto-resolved; you do NOT need to call vo_target_resolve first."
            ),
            examples=["M87", "Cygnus A", "187.7059 12.3911"],
        ),
    ],
    service: Annotated[
        Literal["image", "catalog"],
        Field(
            description=(
                "'image' -> Simple Image Access (rows carry image/cutout "
                "access_urls). 'catalog' -> Simple Cone Search (source rows)."
            ),
        ),
    ] = "image",
    waveband: Annotated[
        str | None,
        Field(
            description=(
                "Optional waveband to auto-select the archive — 'radio', "
                "'optical', 'infrared', 'millimeter'. Omit to use the "
                "highest-priority archive offering this service."
            ),
            examples=["radio", "optical"],
        ),
    ] = None,
    radius_deg: Annotated[
        float,
        Field(ge=0.0001, le=5.0, description="Search radius / field size in degrees. Default 0.1."),
    ] = 0.1,
    archive: Annotated[
        str | None,
        Field(
            description=(
                "Optional short_name override ('nrao', 'datalab') to skip "
                "auto-selection. Use when you already know the archive."
            ),
            examples=["nrao", "datalab"],
        ),
    ] = None,
    maxrec: Annotated[
        int, Field(ge=1, le=10_000, description="Hard cap on rows returned. Default 1_000.")
    ] = 1_000,
) -> dict:
    """Find observations of a target in one call (resolve -> select -> search).

    A purpose-driven facade over vo_target_resolve + vo_archive_list +
    vo_sia_search / vo_cone_search. Pass an object name (auto-resolved) or
    explicit 'RA DEC'; optionally steer archive choice with `waveband` or an
    explicit `archive`.

    Returns the standard inline tabular envelope (same shape as vo_sia_search /
    vo_cone_search — typed `columns`, `rows`, explicit `truncated` bool) plus:

      - `resolved`: {target, ra, dec, frame} — the coordinates actually used.
      - `plan`: {service, chosen_archive, endpoint, alternatives, usage_notes}
        — how the archive was picked, and its curated gotchas. Read
        `plan.usage_notes` before trusting the rows.

    Soft-fails (no error_class) when a name can't be resolved
    ({"resolved": false, ...}) or no archive matches the filter
    ({"count": 0, "hint": ...}) — recover by adjusting the target/filter or
    dropping to the atomic tools with an explicit endpoint.
    """
    target_clean = target.strip()
    if not target_clean:
        raise ValidationError(
            message="'target' must be non-empty. Provide an object name or 'RA DEC'.",
        )

    ra, dec = _coerce_or_resolve(target_clean)
    if ra is None or dec is None:
        return {
            "resolved": False,
            "target": target_clean,
            "message": (
                "Could not resolve target via CDS Sesame (tried SIMBAD, NED, VizieR). "
                "Try an alternate designation, or pass explicit 'RA DEC' in decimal degrees."
            ),
        }

    candidates = _rank_candidates(service=service, waveband=waveband, override=archive)
    if not candidates:
        return _no_candidate_payload(service=service, waveband=waveband, override=archive)

    chosen = candidates[0]
    # _rank_candidates only keeps archives whose service URL is set, so the
    # endpoint is non-None here — assert it to narrow for the type checker.
    if service == "image":
        endpoint = chosen.sia_url
        assert endpoint is not None
        table = _get_sia().search(
            endpoint=endpoint,
            ra=ra,
            dec=dec,
            size_deg=radius_deg,
            band=None,
            fmt=None,
            maxrec=maxrec,
            version="auto",
        )
    else:
        endpoint = chosen.scs_url
        assert endpoint is not None
        table = _get_cone().search(
            endpoint=endpoint,
            ra=ra,
            dec=dec,
            radius_deg=radius_deg,
            maxrec=maxrec,
        )

    envelope = shape_table(table, archive=chosen.short_name, maxrec=maxrec)
    envelope["resolved"] = {"target": target_clean, "ra": ra, "dec": dec, "frame": "icrs"}
    envelope["plan"] = {
        "service": service,
        "chosen_archive": chosen.short_name,
        "endpoint": endpoint,
        "alternatives": [c.short_name for c in candidates[1:3]] or None,
        "usage_notes": note_texts(chosen.usage_notes) or None,
    }
    return envelope


vo_find_observations.__doc__ = (vo_find_observations.__doc__ or "") + _ERROR_DOCSTRING
