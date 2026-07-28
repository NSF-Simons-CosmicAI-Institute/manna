"""Gaia ARI Heidelberg (Simple Cone Search mirror)."""

from manna.archives._model import Archive

ARCHIVE = Archive(
    short_name="gaia_ari",
    display_name="Gaia ARI Heidelberg",
    host_substrings=("gaia.ari.uni-heidelberg.de",),
    scs_url="https://gaia.ari.uni-heidelberg.de/cone/gaiadr2?",
    waveband="optical",
    description=(
        "Heidelberg's Gaia mirror — exposes a Simple Cone Search endpoint for legacy clients."
    ),
    priority=70,
)
