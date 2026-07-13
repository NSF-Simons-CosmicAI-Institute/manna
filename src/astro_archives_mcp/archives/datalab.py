"""NOIRLab Astro Data Lab archive."""

from astro_archives_mcp.archives._model import Archive, Schema

ARCHIVE = Archive(
    short_name="datalab",
    display_name="NOIRLab Astro Data Lab",
    host_substrings=("datalab.noirlab",),
    tap_url="https://datalab.noirlab.edu/tap",
    # SIA 1.0 (per-survey endpoints under /sia/...). coadd_all searches
    # every coadded survey at once; vo_sia_search reaches it via its
    # SIA1 fallback.
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
        "Data Lab hosts ~180 services across SCS / SIA / TAP / VOS, "
        "spanning surveys including NSC DR1/DR2, SMASH DR1/DR2, "
        "DES DR1/DR2 + SVA1, DECaPS DR1/DR2, Legacy Surveys DR8–DR10, "
        "Gaia DR1/DR2/EDR3/DR3, SDSS DR12–DR17, SkyMapper DR1/2/4, "
        "2MASS PSC/XSC, AllWISE, unWISE, UKIDSS DR11+, VHS DR5, "
        "Hipparcos, Tycho-2, and Stripe82 cross-matches.",
        "Data Lab is fully registered in the IVOA registry under "
        "`ivo://noirlab.edu/...` — vo_registry_search and "
        "vo_registry_describe both work normally.",
        "Each survey has its own schema namespace (smash_dr2, nsc_dr2, "
        "des_dr2, decaps_dr2, etc.). Inside each schema, the main "
        "table is usually `<schema>.object`.",
        "SCS URL convention is `/scs/<dataset>/<table>` (e.g. "
        "`/scs/nsc_dr2/object`), NOT `/scs/<dataset>`. The shorter "
        "form returns 404.",
        "ADQL geometry functions (POINT, CIRCLE, CONTAINS, INTERSECTS, "
        "DISTANCE) are NOT translated — the backend passes them straight "
        "to PostgreSQL, so `CONTAINS(POINT('ICRS', ra, dec), CIRCLE(...))` "
        "fails with `function point(...) does not exist`. For a true "
        "indexed cone use the Q3C functions the tables are clustered on, "
        "compared to a boolean literal: `WHERE q3c_radial_query(ra, dec, "
        "<ra0>, <dec0>, <radius_deg>) = 't'`. The `= 't'` is required — a "
        "bare `q3c_radial_query(...)` predicate is rejected by the ADQL "
        "parser. q3c_ellipse_query / q3c_poly_query exist too. A "
        "bounding-box (`ra BETWEEN ... AND dec BETWEEN ...`) also works "
        "but returns a box, not a circle.",
        "Image access is SIA 1.0 (not SIA2), exposed per survey/image-type: "
        "https://datalab.noirlab.edu/sia/coadd_all (all coadds at once), "
        "or specific ones like /sia/coadd/ls_dr9, /sia/coadd/des_dr1, "
        "/sia/calibrated/smash_dr2. vo_sia_search drives these via its "
        "SIA1 fallback (version='auto'), or pass version='1'. Returned "
        "access_url values are on-the-fly cutout links (/svc/cutout?...) "
        "you fetch client-side (the server does not download images).",
        "vo_cone_search works (e.g. /scs/nsc_dr2/object) but SCS returns "
        "EVERY column of these very wide tables (nsc_dr2.object has ~99). "
        "When you need only a few columns, prefer a TAP query with an "
        "explicit column list plus a q3c_radial_query filter.",
        "Bright/extended sources in NSC DR2 (e.g. BCGs, large "
        "galaxies) commonly carry blend flags (flags=3). Filtering "
        "with flags=0 silently excludes them. When searching for "
        "bright objects in dense regions (cluster cores, etc.), drop "
        "the flag filter or post-filter client-side.",
    ),
    schemas=(
        Schema(
            archive="datalab",
            table="nsc_dr2.object",
            notes=(
                "For a cone, the simplest reliable filter is "
                "q3c_radial_query(ra, dec, <ra0>, <dec0>, <radius_deg>) = 't' "
                "(the table is Q3C-clustered on ra/dec). ADQL CONTAINS/POINT do "
                "NOT work here — see the datalab usage_notes.",
                "Pre-computed index columns also exist for coarse bucketing: htm9 "
                "(~10 arcmin), ring256 (~14 arcmin), nest4096 (~52 arcsec). Usable "
                "in bounding-box / equality predicates.",
                "~99 columns wide. Always project an explicit column list; "
                "SELECT * (or an SCS cone) returns the whole row.",
            ),
        ),
        Schema(
            archive="datalab",
            table="smash_dr2.object",
            notes=(
                "SCS URL is https://datalab.noirlab.edu/scs/smash_dr2/object, "
                "NOT /scs/smash_dr2. The dataset-only path returns 404.",
            ),
            cross_refs=(("datalab", "nsc_dr2.object"),),
        ),
        Schema(
            archive="datalab",
            table="tap_schema.tables",
            notes=(
                "Crossmatch tables (nearest-neighbor 1.5 arcsec against "
                "AllWISE / Gaia DR3 / NSC DR2 / SDSS DR17 / unWISE DR1) carry "
                "an x1p5 suffix, e.g. "
                "phat_v3.x1p5__phot_mod__gaia_dr3__gaia_source.",
            ),
        ),
    ),
    priority=10,
)
