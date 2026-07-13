"""Sloan Digital Sky Survey."""

from astro_archives_mcp.archives._model import Archive

ARCHIVE = Archive(
    short_name="sdss",
    display_name="Sloan Digital Sky Survey",
    host_substrings=("sdss.org",),
    waveband="optical",
    description="SDSS imaging and spectroscopic archive.",
    priority=80,
)
