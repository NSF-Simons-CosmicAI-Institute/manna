"""ESA Gaia Archive."""

from manna.archives._audit import Audit
from manna.archives._count import ContainsPoint, CountTarget
from manna.archives._model import Archive, Note

ARCHIVE = Archive(
    short_name="gaia",
    display_name="ESA Gaia Archive",
    host_substrings=("gea.esac.esa",),
    tap_url="https://gea.esac.esa.int/tap-server/tap",
    waveband="optical",
    description="Authoritative Gaia mission archive at ESAC.",
    notable_tables=("gaiadr3.gaia_source", "gaiadr2.gaia_source"),
    usage_notes=(
        Note(
            id="dr3-default-table",
            text=(
                "Newer Gaia releases supersede older ones for most use cases — "
                "default to gaiadr3.gaia_source, the default queryable table."
            ),
            audit=Audit.probe(
                expect="ok",
                adql="SELECT TOP 1 source_id FROM gaiadr3.gaia_source",
            ),
        ),
        Note(
            id="dr2-schema-exists",
            text=(
                "Each Gaia data release is a separate schema (gaiadr2.*, "
                "gaiadr3.*, gaiaedr3.*, etc.) — e.g. gaiadr2.gaia_source still "
                "exists alongside gaiadr3.gaia_source."
            ),
            audit=Audit.probe(
                expect="nonempty",
                adql=(
                    "SELECT table_name FROM tap_schema.tables "
                    "WHERE table_name = 'gaiadr2.gaia_source'"
                ),
            ),
        ),
        Note(
            id="source-id-join-key",
            text=(
                "`source_id` is the canonical join key. Astrometric solutions, "
                "photometry, and radial velocities are split across multiple "
                "tables — JOIN to gaia_source on source_id."
            ),
            audit=Audit.manual(
                "source_id as the canonical join key across split astrometry/"
                "photometry/radial-velocity tables is a structural fact about "
                "the data model, not a single falsifiable probe."
            ),
        ),
    ),
    count_target=CountTarget(
        table="gaiadr3.gaia_source",
        geometry=ContainsPoint("ra", "dec"),
        count_expr="COUNT(*)",
        mode="sync",
    ),
    priority=60,
)
