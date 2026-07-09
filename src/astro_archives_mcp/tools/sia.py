"""Tools for IVOA Simple Image Access."""

from typing import Annotated, Literal

from pydantic import Field

from astro_archives_mcp._archive_label import archive_label
from astro_archives_mcp.backends.sia import SiaClient
from astro_archives_mcp.errors import wrap_tool_errors
from astro_archives_mcp.known_archives import (
    sia_endpoint_description,
    sia_endpoint_urls,
)
from astro_archives_mcp.shaper import shape_table
from astro_archives_mcp.tools._constants import _ERROR_DOCSTRING

_sia: SiaClient | None = None


def _get_sia() -> SiaClient:
    """Lazy accessor so tests can patch SiaClient without import-time side effects."""
    global _sia
    if _sia is None:
        _sia = SiaClient()
    return _sia


@wrap_tool_errors
def vo_sia_search(
    endpoint: Annotated[
        str,
        Field(
            description=sia_endpoint_description(),
            examples=sia_endpoint_urls()[:2],
        ),
    ],
    ra: Annotated[float, Field(description="Right ascension (ICRS), degrees.")],
    dec: Annotated[float, Field(description="Declination (ICRS), degrees.")],
    size_deg: Annotated[
        float,
        Field(ge=0.0001, le=5.0, description="Field-of-view size in degrees."),
    ],
    band: Annotated[
        str | None,
        Field(
            description="Optional waveband filter (e.g. 'optical', 'infrared').",
            examples=["optical"],
        ),
    ] = None,
    fmt: Annotated[
        str | None,
        Field(
            description="Optional image format (e.g. 'image/fits').",
            examples=["image/fits"],
        ),
    ] = None,
    maxrec: Annotated[
        int, Field(ge=1, le=10_000, description="Hard cap on rows returned. Default 1_000.")
    ] = 1_000,
    version: Annotated[
        Literal["auto", "1", "2"],
        Field(
            description=(
                "SIA protocol version. 'auto' (default) tries SIA 2.0 and "
                "falls back to SIA 1.0 when the endpoint isn't SIA2 (e.g. "
                "NOIRLab Data Lab is SIA 1.0). Force with '2' or '1'. The "
                "'band' filter applies to SIA2 only."
            ),
        ),
    ] = "auto",
) -> dict:
    """Discover images at a sky position via Simple Image Access (SIA 2.0 or 1.0).

    Returns the inline tabular envelope. Each row is image metadata; the
    `access_url` column points at the image (a FITS file, or a cutout-service
    URL for archives like Data Lab). The server does not download images —
    fetch an access_url client-side (e.g. astropy.io.fits.open(access_url)).

    Most archives speak SIA2; NOIRLab Data Lab speaks SIA1. With the default
    version='auto' you don't need to know which — SIA2 is tried first and
    SIA1 is used as a fallback.

    For all-sky discovery first, see vo_registry_search with
    servicetype='sia'.
    """
    table = _get_sia().search(
        endpoint=endpoint,
        ra=ra,
        dec=dec,
        size_deg=size_deg,
        band=band,
        fmt=fmt,
        maxrec=maxrec,
        version=version,
    )
    return shape_table(table, archive=archive_label(endpoint), maxrec=maxrec)


vo_sia_search.__doc__ = (vo_sia_search.__doc__ or "") + _ERROR_DOCSTRING
