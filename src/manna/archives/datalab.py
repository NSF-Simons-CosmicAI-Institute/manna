"""NOIRLab Astro Data Lab archive."""

from manna.archives._audit import Audit
from manna.archives._model import Archive, Note, Schema, Trap

ARCHIVE = Archive(
    short_name="datalab",
    display_name="NOIRLab Astro Data Lab",
    host_substrings=("datalab.noirlab",),
    tap_url="https://datalab.noirlab.edu/tap",
    sia_url="https://datalab.noirlab.edu/sia/coadd_all",
    waveband="optical",
    description=("Optical surveys: NSC, SMASH, DECaPS, DES. Large object catalogs."),
    notable_tables=(
        "nsc_dr2.object",
        "smash_dr2.object",
        "des_dr2.main",
        "decaps_dr2.object",
    ),
    usage_notes=(
        Note(
            id="services-breadth",
            text=(
                "Data Lab hosts ~180 services across SCS / SIA / TAP / VOS, spanning "
                "NSC DR1/DR2, SMASH DR1/DR2, DES DR1/DR2 + SVA1, DECaPS DR1/DR2, "
                "Legacy Surveys DR8–DR10, Gaia DR1/DR2/EDR3/DR3, SDSS DR12–DR17, "
                "SkyMapper DR1/2/4, 2MASS PSC/XSC, AllWISE, unWISE, UKIDSS DR11+, "
                "VHS DR5, Hipparcos, Tycho-2, and Stripe82 cross-matches."
            ),
            audit=Audit.manual("Service-count/breadth claim — not a single-probe check."),
        ),
        Note(
            id="ivoa-registered",
            text=(
                "Data Lab is fully registered in the IVOA registry under "
                "`ivo://noirlab.edu/...` — vo_registry_search and vo_registry_describe "
                "both work normally."
            ),
            audit=Audit.manual("Registry-presence claim — verify via vo_registry_search."),
        ),
        Note(
            id="schema-object-convention",
            text=(
                "Each survey has its own schema namespace (smash_dr2, nsc_dr2, des_dr2, "
                "decaps_dr2, …). Inside each, the main table is usually `<schema>.object` "
                "(e.g. nsc_dr2.object)."
            ),
            audit=Audit.probe(
                expect="nonempty",
                adql="SELECT table_name FROM tap_schema.tables WHERE table_name = 'nsc_dr2.object'",
            ),
        ),
        Note(
            id="scs-url-convention",
            text=(
                "SCS URL convention is `/scs/<dataset>/<table>` (e.g. `/scs/nsc_dr2/object`), "
                "NOT `/scs/<dataset>`. The shorter form returns 404."
            ),
            audit=Audit.manual("SCS URL routing — an HTTP-path convention, not a TAP probe."),
        ),
        Note(
            id="geometry-contains-untranslated",
            text=(
                "ADQL geometry functions (POINT, CIRCLE, CONTAINS, INTERSECTS, DISTANCE) are "
                "NOT translated — the backend passes them to PostgreSQL, so "
                "CONTAINS(POINT('ICRS', ra, dec), CIRCLE(...)) fails with "
                "`function point(...) does not exist`."
            ),
            audit=Audit.probe(
                expect="error",
                adql=(
                    "SELECT TOP 1 ra, dec FROM nsc_dr2.object "
                    "WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', 10.0, 10.0, 0.01)) = 1"
                ),
            ),
            # Loud by mechanism, silent in effect (so: no triggers): the raw
            # PostgreSQL complaint ("function point(...) does not exist") never
            # hints that q3c is the answer, so the model can't recover from it.
            # Prevention is what exp_a_matrix measured working (C=0/15 blind ->
            # D=12/15 injected).
            trap=Trap(
                guidance=(
                    "ADQL geometry (CONTAINS/CIRCLE/POINT) is NOT translated and errors. "
                    "For a cone use q3c_radial_query(ra, dec, <ra0>, <dec0>, <radius_deg>) = 't'; "
                    "a ra/dec BETWEEN box also works but is a box, not a circle."
                ),
            ),
        ),
        Note(
            id="geometry-q3c-literal-ok",
            text=(
                "For a true indexed cone use q3c_radial_query(ra, dec, <ra0>, <dec0>, "
                "<radius_deg>) = 't'. The `= 't'` literal is required."
            ),
            audit=Audit.probe(
                expect="ok",
                adql=(
                    "SELECT TOP 1 ra, dec FROM nsc_dr2.object "
                    "WHERE q3c_radial_query(ra, dec, 10.0, 10.0, 0.01) = 't'"
                ),
            ),
        ),
        Note(
            id="geometry-q3c-bare-rejected",
            text="A bare q3c_radial_query(...) predicate (without `= 't'`) is rejected by the ADQL parser.",
            audit=Audit.probe(
                expect="error",
                adql=(
                    "SELECT TOP 1 ra, dec FROM nsc_dr2.object "
                    "WHERE q3c_radial_query(ra, dec, 10.0, 10.0, 0.01)"
                ),
            ),
        ),
        Note(
            id="geometry-q3c-ellipse-exists",
            text="q3c_ellipse_query / q3c_poly_query exist too for non-circular regions.",
            audit=Audit.probe(
                expect="ok",
                adql=(
                    "SELECT TOP 1 ra, dec FROM nsc_dr2.object "
                    "WHERE q3c_ellipse_query(ra, dec, 10.0, 10.0, 0.02, 0.5, 45.0) = 't'"
                ),
            ),
        ),
        Note(
            id="geometry-bbox-ok",
            text=(
                "A bounding box (ra BETWEEN ... AND dec BETWEEN ...) also works, "
                "but returns a box, not a circle."
            ),
            audit=Audit.probe(
                expect="ok",
                adql=(
                    "SELECT TOP 1 ra, dec FROM nsc_dr2.object "
                    "WHERE ra BETWEEN 9.99 AND 10.01 AND dec BETWEEN 9.99 AND 10.01"
                ),
            ),
        ),
        Note(
            id="image-access-sia1",
            text=(
                "Image access is SIA 1.0 (not SIA2), exposed per survey/image-type: "
                "/sia/coadd_all (all coadds), or /sia/coadd/ls_dr9, /sia/coadd/des_dr1, "
                "/sia/calibrated/smash_dr2. vo_sia_search drives these via its SIA1 fallback "
                "(version='auto'). Returned access_url values are on-the-fly cutout links "
                "you fetch client-side."
            ),
            audit=Audit.manual("SIA 1.0 image-access recipe — not a TAP probe."),
        ),
        Note(
            id="cone-returns-all-columns",
            text=(
                "vo_cone_search works (e.g. /scs/nsc_dr2/object) but SCS returns EVERY column "
                "of these very wide tables. When you need only a few columns, prefer a TAP "
                "query with an explicit column list plus a q3c_radial_query filter."
            ),
            audit=Audit.manual("SCS-returns-all-columns behaviour — advisory, not a TAP probe."),
        ),
        Note(
            id="nsc-blend-flags-column",
            text=(
                "Bright/extended sources in NSC DR2 (BCGs, large galaxies) commonly carry "
                "blend flags (flags=3). Filtering with flags=0 silently excludes them; drop "
                "the flag filter or post-filter client-side in dense regions."
            ),
            audit=Audit.count(table="nsc_dr2.object", columns=("flags",)),
        ),
        Note(
            id="x1p5-crossmatch-tables",
            text=(
                "Crossmatch tables (nearest-neighbor 1.5 arcsec against AllWISE / Gaia DR3 / "
                "NSC DR2 / SDSS DR17 / unWISE DR1) carry an x1p5 suffix, e.g. "
                "phat_v3.x1p5__phot_mod__gaia_dr3__gaia_source."
            ),
            audit=Audit.probe(
                expect="nonempty",
                adql="SELECT TOP 1 table_name FROM tap_schema.tables WHERE table_name LIKE '%x1p5%'",
            ),
        ),
    ),
    schemas=(
        Schema(
            archive="datalab",
            table="nsc_dr2.object",
            notes=(
                Note(
                    id="nsc-cone-q3c",
                    text=(
                        "For a cone, the simplest reliable filter is "
                        "q3c_radial_query(ra, dec, <ra0>, <dec0>, <radius_deg>) = 't' "
                        "(the table is Q3C-clustered on ra/dec). ADQL CONTAINS/POINT do NOT "
                        "work here — see the datalab usage_notes."
                    ),
                    audit=Audit.manual(
                        "Same live check as datalab usage_note geometry-q3c-literal-ok; advisory here."
                    ),
                ),
                Note(
                    id="nsc-index-columns",
                    text=(
                        "Pre-computed index columns exist for coarse bucketing: htm9 (~10 arcmin), "
                        "ring256 (~14 arcmin), nest4096 (~52 arcsec). Usable in bounding-box / "
                        "equality predicates."
                    ),
                    audit=Audit.count(
                        table="nsc_dr2.object", columns=("htm9", "ring256", "nest4096")
                    ),
                ),
                Note(
                    id="nsc-99-columns-wide",
                    text=(
                        "~99 columns wide. Always project an explicit column list; SELECT * "
                        "(or an SCS cone) returns the whole row."
                    ),
                    audit=Audit.manual("Column-count/width advisory — not a drift probe."),
                ),
            ),
        ),
        Schema(
            archive="datalab",
            table="smash_dr2.object",
            notes=(
                Note(
                    id="smash-object-table",
                    text="smash_dr2.object exists (the per-survey object table for SMASH DR2).",
                    audit=Audit.probe(
                        expect="nonempty",
                        adql=(
                            "SELECT table_name FROM tap_schema.tables "
                            "WHERE table_name = 'smash_dr2.object'"
                        ),
                    ),
                ),
                Note(
                    id="smash-scs-url",
                    text=(
                        "SCS URL is https://datalab.noirlab.edu/scs/smash_dr2/object, NOT "
                        "/scs/smash_dr2. The dataset-only path returns 404."
                    ),
                    audit=Audit.manual(
                        "SCS URL routing — an HTTP-path convention, not a TAP probe."
                    ),
                ),
            ),
            cross_refs=(("datalab", "nsc_dr2.object"),),
        ),
        Schema(
            archive="datalab",
            table="tap_schema.tables",
            notes=(
                Note(
                    id="x1p5-crossmatch-suffix",
                    text=(
                        "Crossmatch tables (nearest-neighbor 1.5 arcsec against AllWISE / Gaia DR3 "
                        "/ NSC DR2 / SDSS DR17 / unWISE DR1) carry an x1p5 suffix, e.g. "
                        "phat_v3.x1p5__phot_mod__gaia_dr3__gaia_source."
                    ),
                    audit=Audit.manual(
                        "Same live check as the datalab usage_note x1p5-crossmatch-tables; "
                        "table-level cross-reference here."
                    ),
                ),
            ),
        ),
    ),
    priority=10,
)
