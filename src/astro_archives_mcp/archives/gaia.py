"""ESA Gaia Archive."""

from astro_archives_mcp.archives._model import Archive

ARCHIVE = Archive(
    short_name="gaia",
    display_name="ESA Gaia Archive",
    host_substrings=("gea.esac.esa",),
    tap_url="https://gea.esac.esa.int/tap-server/tap",
    waveband="optical",
    description="Authoritative Gaia mission archive at ESAC.",
    notable_tables=("gaiadr3.gaia_source", "gaiadr2.gaia_source"),
    usage_notes=(
        "Each Gaia data release is a separate schema (gaiadr2.*, "
        "gaiadr3.*, gaiaedr3.*, etc.). Newer releases supersede older "
        "ones for most use cases — default to gaiadr3.gaia_source.",
        "`source_id` is the canonical join key. Astrometric solutions, "
        "photometry, and radial velocities are split across multiple "
        "tables — JOIN to gaia_source on source_id.",
    ),
    priority=60,
)
