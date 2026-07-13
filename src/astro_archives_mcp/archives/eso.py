"""ESO Science Archive."""

from astro_archives_mcp.archives._model import Archive

ARCHIVE = Archive(
    short_name="eso",
    display_name="ESO Science Archive",
    host_substrings=("archive.eso",),
    tap_url="https://archive.eso.org/tap_obs",
    waveband="optical",
    description="European Southern Observatory archive (VLT, La Silla).",
    notable_tables=("ivoa.ObsCore",),
    priority=40,
)
