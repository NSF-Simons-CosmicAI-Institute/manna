"""Tools for IVOA Simple Cone Search."""

from typing import Annotated

from pydantic import Field

from astro_archives_mcp._archive_label import archive_label
from astro_archives_mcp.archives._endpoints import (
    scs_endpoint_description,
    scs_endpoint_urls,
)
from astro_archives_mcp.backends.cone import ConeSearchClient
from astro_archives_mcp.errors import wrap_tool_errors
from astro_archives_mcp.shaper import shape_table
from astro_archives_mcp.tools._constants import _ERROR_DOCSTRING

_cone: ConeSearchClient | None = None


def _get_cone() -> ConeSearchClient:
    """Lazy accessor so tests can patch ConeSearchClient without import-time side effects."""
    global _cone
    if _cone is None:
        _cone = ConeSearchClient()
    return _cone


@wrap_tool_errors
def vo_cone_search(
    endpoint: Annotated[
        str,
        Field(
            description=scs_endpoint_description(),
            examples=scs_endpoint_urls()[:2],
        ),
    ],
    ra: Annotated[float, Field(description="Right ascension (ICRS), degrees.")],
    dec: Annotated[float, Field(description="Declination (ICRS), degrees.")],
    radius_deg: Annotated[
        float,
        Field(ge=0.0001, le=10.0, description="Cone radius in degrees."),
    ],
    maxrec: Annotated[
        int, Field(ge=1, le=100_000, description="Hard cap on rows returned. Default 10_000.")
    ] = 10_000,
) -> dict:
    """Run a Simple Cone Search (SCS) against a catalog endpoint.

    Returns the inline tabular envelope, same shape as vo_tap_query.
    For most uses, prefer vo_tap_query — SCS is here for catalogs that
    only expose the legacy protocol.
    """
    table = _get_cone().search(
        endpoint=endpoint,
        ra=ra,
        dec=dec,
        radius_deg=radius_deg,
        maxrec=maxrec,
    )
    return shape_table(table, archive=archive_label(endpoint), maxrec=maxrec)


vo_cone_search.__doc__ = (vo_cone_search.__doc__ or "") + _ERROR_DOCSTRING
