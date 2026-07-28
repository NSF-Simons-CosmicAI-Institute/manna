"""Tool for resolving astronomical object names to sky coordinates.

``vo_target_resolve(name)`` queries CDS Sesame (SIMBAD → NED → VizieR) and
returns RA/Dec in ICRS decimal degrees, ready for ADQL CIRCLE predicates or
``vo_cone_search``. Soft-fails with ``resolved: false`` when the name is
unknown so the LLM can try an alternate designation.
"""

from typing import Annotated

from pydantic import Field

from manna.backends.resolver import ResolverClient
from manna.errors import ValidationError, wrap_tool_errors
from manna.tools._constants import _ERROR_DOCSTRING

_resolver: ResolverClient | None = None


def _get_resolver() -> ResolverClient:
    """Lazy accessor so tests can patch ResolverClient without import-time side effects."""
    global _resolver
    if _resolver is None:
        _resolver = ResolverClient()
    return _resolver


@wrap_tool_errors
def vo_target_resolve(
    name: Annotated[
        str,
        Field(
            description=(
                "Astronomical object name to resolve to sky coordinates. "
                "Uses the CDS Sesame service (queries SIMBAD, then NED, "
                "then VizieR). Common name styles all work: Messier numbers "
                "(M87), NGC/IC designations, IAU names (3C 273), proper "
                "names (Cygnus A)."
            ),
            examples=["NGC 1275", "Cygnus A", "M87", "3C 273"],
        ),
    ],
) -> dict:
    """Resolve an object name to RA/Dec (ICRS, decimal degrees).

    Returns ``ra`` and ``dec`` suitable for ``CONTAINS(POINT('ICRS',ra,dec),
    CIRCLE('ICRS',<ra>,<dec>,<radius>))=1`` ADQL predicates or as the
    positional input to ``vo_cone_search``.

    On miss returns ``{"resolved": false, ...}`` — try an alternate
    designation or use ``vo_registry_search`` to locate a catalog by keyword.
    """
    name_clean = name.strip()
    if not name_clean:
        raise ValidationError(
            message="'name' must be non-empty. Provide an astronomical object name.",
        )

    result = _get_resolver().resolve(name_clean)
    if result is None:
        return {
            "resolved": False,
            "name": name_clean,
            "message": (
                "Name not found in CDS Sesame (tried SIMBAD, NED, VizieR). "
                "Check spelling or try an alternate designation."
            ),
        }

    ra, dec = result
    return {
        "resolved": True,
        "name": name_clean,
        "ra": ra,
        "dec": dec,
        "frame": "icrs",
        "unit": "deg",
    }


vo_target_resolve.__doc__ = (vo_target_resolve.__doc__ or "") + _ERROR_DOCSTRING
