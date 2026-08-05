"""ESO Science Archive."""

from manna.archives._audit import Audit
from manna.archives._count import ContainsPoint, CountTarget
from manna.archives._model import Archive, Note

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
                "ObsCore is published as the mixed-case ivoa.ObsCore table. "
                "Table-name matching is case-insensitive here (ivoa.obscore "
                "works identically, verified live) — use either; just don't "
                "be surprised by the mixed-case name in listings."
            ),
            audit=Audit.probe(
                expect="ok",
                adql="SELECT TOP 1 obs_id FROM ivoa.obscore",
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
    count_target=CountTarget(
        table="ivoa.ObsCore",
        geometry=ContainsPoint("s_ra", "s_dec"),
        count_expr="COUNT(*)",
        mode="auto",
    ),
    priority=40,
)
