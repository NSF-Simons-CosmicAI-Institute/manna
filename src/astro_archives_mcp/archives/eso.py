"""ESO Science Archive."""

from astro_archives_mcp.archives._audit import Audit
from astro_archives_mcp.archives._model import Archive, Note

ARCHIVE = Archive(
    short_name="eso",
    display_name="ESO Science Archive",
    host_substrings=("archive.eso",),
    tap_url="https://archive.eso.org/tap_obs",
    waveband="optical",
    description="European Southern Observatory archive (VLT, La Silla).",
    notable_tables=("ivoa.ObsCore",),
    usage_notes=(
        Note(
            id="obscore-mixedcase",
            text=(
                "ESO exposes ObsCore at the mixed-case ivoa.ObsCore table "
                "(note the capitalization)."
            ),
            audit=Audit.probe(
                expect="ok",
                adql="SELECT TOP 1 * FROM ivoa.ObsCore",
            ),
        ),
        Note(
            id="minimal-curation",
            text=(
                "ESO curation is minimal — only the mixed-case ObsCore location "
                "is captured here; agents may still hit uncurated TAP quirks "
                "(see issue #41)."
            ),
            audit=Audit.manual("Advisory about curation coverage — not a single-probe check."),
        ),
    ),
    priority=40,
)
