"""Canadian Astronomy Data Centre."""

from astro_archives_mcp.archives._model import Archive

ARCHIVE = Archive(
    short_name="cadc",
    display_name="Canadian Astronomy Data Centre",
    host_substrings=("cadc-ccda.hia-iha", "ws.cadc-ccda"),
    tap_url="https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/tap",
    sia_url="https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/sia",
    waveband="multi",
    description=("Multi-mission archive — TESS, JWST, CFHT, HST imaging available via SIA2."),
    usage_notes=(
        "SIA2 results' `access_url` column points at a DataLink VOTable, "
        "NOT directly at the FITS file. Check `access_format` — if it "
        "contains `content=datalink`, you must follow the indirection.",
        "Datalink follow-through recipe (verified live): "
        "(1) GET the access_url with Accept: application/x-votable+xml; "
        "(2) parse the VOTable rows; "
        "(3) find the row where semantics == '#this' — that's the "
        "primary image; "
        "(4) GET its access_url to get the real FITS bytes "
        "(the destination may be on a different host like "
        "mast.stsci.edu or S3 — follow redirects).",
        "Use `obs_collection` to filter by mission: 'TESS', 'JWST', 'CFHT', 'HST', etc.",
    ),
    priority=50,
)
