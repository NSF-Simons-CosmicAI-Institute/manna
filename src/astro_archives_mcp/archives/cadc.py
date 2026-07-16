"""Canadian Astronomy Data Centre."""

from astro_archives_mcp.archives._audit import Audit
from astro_archives_mcp.archives._model import Archive, Note

ARCHIVE = Archive(
    short_name="cadc",
    display_name="Canadian Astronomy Data Centre",
    host_substrings=("cadc-ccda.hia-iha", "ws.cadc-ccda"),
    tap_url="https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/argus",
    sia_url="https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/sia",
    waveband="multi",
    description=("Multi-mission archive — TESS, JWST, CFHT, HST imaging available via SIA2."),
    usage_notes=(
        Note(
            id="tap-at-argus",
            text=(
                "CADC TAP is served at /argus "
                "(https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/argus) — the old "
                "/tap path is a hard 404. It serves the caom2.* tables (e.g. "
                "caom2.Observation) plus an ivoa.ObsCore view."
            ),
            audit=Audit.probe(
                expect="ok",
                adql="SELECT TOP 1 collection FROM caom2.Observation",
            ),
        ),
        Note(
            id="sia2-datalink-indirection",
            text=(
                "SIA2 results' `access_url` column points at a DataLink VOTable, "
                "NOT directly at the FITS file. Check `access_format` — if it "
                "contains `content=datalink`, you must follow the indirection."
            ),
            audit=Audit.manual(
                "SIA2 access_url indirection depends on inspecting a live "
                "access_format value — not a single ADQL/tap_schema probe."
            ),
        ),
        Note(
            id="datalink-follow-through",
            text=(
                "Datalink follow-through recipe (verified live): "
                "(1) GET the access_url with Accept: application/x-votable+xml; "
                "(2) parse the VOTable rows; "
                "(3) find the row where semantics == '#this' — that's the "
                "primary image; "
                "(4) GET its access_url to get the real FITS bytes "
                "(the destination may be on a different host like "
                "mast.stsci.edu or S3 — follow redirects)."
            ),
            audit=Audit.manual(
                "Multi-step client download recipe (GET -> parse VOTable -> "
                "follow indirection to the real FITS) — not a single ADQL/TAP probe."
            ),
        ),
        Note(
            id="collection-column",
            text=(
                "To filter by mission on caom2.Observation use `collection` "
                "('TESS', 'JWST', 'CFHT', 'HST', ...). The ObsCore-standard "
                "`obs_collection` column exists only on the ivoa.ObsCore view "
                "— referencing it on caom2.Observation errors. Match the "
                "column to the table you query."
            ),
            audit=Audit.probe(
                expect="nonempty",
                adql=("SELECT TOP 1 collection FROM caom2.Observation WHERE collection = 'JWST'"),
            ),
        ),
    ),
    priority=50,
)
