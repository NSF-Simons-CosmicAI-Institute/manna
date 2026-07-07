"""Curated per-table schema knowledge base (Tier 2).

SCHEMA_KB stores table-specific SURPRISES only — missing standard columns,
value enums for filterable fields, spatial index columns, naming conventions.
Archive-level quirks (ADQL bugs, endpoint routing, mode requirements) belong
in known_archives.Archive.usage_notes instead, NOT here.

Live introspection via vo_registry_describe is the authoritative source for
the full column list; this KB only adds human-curated context not derivable
from the schema alone.

Forking note: deployments that only target a subset of archives should prune
SCHEMA_KB to just the relevant entries (same as pruning KNOWN_ARCHIVES).
No other file needs to be touched.

To add a new entry: append a Schema(...) to SCHEMA_KB.
"""

from dataclasses import dataclass, field

from astro_archives_mcp._serialization import dataclass_to_jsonable_dict


@dataclass(frozen=True)
class Schema:
    """Curated knowledge about ONE table at one archive."""

    archive: str
    table: str

    missing_standard_columns: tuple[str, ...] = ()
    value_enums: dict[str, tuple[str, ...]] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    # 2-tuple form, not "archive:table" strings, to avoid parsing fragility.
    cross_refs: tuple[tuple[str, str], ...] = ()


SCHEMA_KB: tuple[Schema, ...] = (
    Schema(
        archive="alma",
        table="ivoa.obscore",
        # Extended ObsCore 1.1 view — all mandatory ObsCore columns present.
        value_enums={
            # Controlled vocabulary (full-table DISTINCT). Empty string also
            # occurs for rows with no assigned category.
            "scientific_category": (
                "Active galaxies",
                "Cosmology",
                "Disks and planet formation",
                "Galaxy evolution",
                "ISM and star formation",
                "Local Universe",
                "Solar system",
                "Stars and stellar evolution",
                "Sun",
            ),
            "dataproduct_type": ("cube", "image"),
            "data_rights": ("Public", "Proprietary"),
            # 'T'/'F' char flags, not SQL booleans.
            "science_observation": ("T", "F"),
            "qa2_passed": ("T", "F"),
        },
        notes=(
            "member_ous_uid identifies a downloadable dataset (Member OUS). "
            "Rows are finer than that — one per spectral window per execution "
            "— so SELECT DISTINCT member_ous_uid is the way to count/collapse "
            "to datasets.",
            "Two spatial columns: s_ra/s_dec is the pointing centre (a point); "
            "s_region is the WKT footprint of the observed field. Use "
            "INTERSECTS(CIRCLE(...), s_region) to catch mosaics and fields "
            "whose centre lies outside a small search radius.",
            "band_list is a space-separated list of ALMA receiver bands "
            "present, e.g. '6' or '3 6 7'. Bands run 1, 3-10 (no band 2). "
            "Beware LIKE '%1%' — it also matches band 10; match an exact token "
            "(band_list = '6') or pad with delimiters.",
            "calib_level: 2 = Member-OUS (per-execution) products, 3 = "
            "Group-OUS (combined) products.",
            "frequency is the tuned sky reference frequency (GHz); "
            "frequency_support holds the full per-spectral-window frequency "
            "ranges. em_min/em_max are the standard ObsCore wavelengths (m).",
        ),
        cross_refs=(("nrao", "tap_schema.obscore"),),
    ),
    Schema(
        archive="alma",
        table="sourcecatalogue.source_cone_search",
        notes=(
            "Calibrator / source flux catalogue (the SCS-backed view), NOT "
            "the observation obscore. Columns: m_ra/m_dec (deg), m_frequency "
            "(Hz), m_flux (Jy), band_name, source_names, catalogue_name.",
            "Filter spatially on m_ra/m_dec. The s_ra_deg/s_dec_deg columns "
            "can be NULL, so CONTAINS(POINT('ICRS', s_ra_deg, s_dec_deg), ...) "
            "raises ORA-13032 (Invalid NULL SDO_GEOMETRY).",
            "band_name includes 'non-ALMA Band' rows (e.g. VLBI catalogue "
            "entries at 8.3/23 GHz) — filter band_name if you only want ALMA "
            "receiver bands.",
        ),
        cross_refs=(("alma", "ivoa.obscore"),),
    ),
    Schema(
        archive="nrao",
        table="tap_schema.obscore",
        missing_standard_columns=("dataproduct_subtype",),
        value_enums={
            "instrument_name": ("EVLA", "VLA", "VLBA", "GBT"),
            "facility_name": ("NRAO",),
        },
    ),
    Schema(
        archive="datalab",
        table="nsc_dr2.object",
        notes=(
            "For a cone, the simplest reliable filter is "
            "q3c_radial_query(ra, dec, <ra0>, <dec0>, <radius_deg>) = 't' "
            "(the table is Q3C-clustered on ra/dec). ADQL CONTAINS/POINT do "
            "NOT work here — see the datalab usage_notes.",
            "Pre-computed index columns also exist for coarse bucketing: htm9 "
            "(~10 arcmin), healpix_ring256 (~14 arcmin), healpix_nest4096 "
            "(~52 arcsec). Usable in bounding-box / equality predicates.",
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
)


def lookup_schema(*, archive: str, table: str) -> Schema | None:
    """Linear scan of SCHEMA_KB. None if no curated entry.

    Matching is exact (case-sensitive) on both archive short_name and
    table name. Same shape as known_archives.by_short_name.
    """
    for s in SCHEMA_KB:
        if s.archive == archive and s.table == table:
            return s
    return None


def schema_to_dict(s: Schema) -> dict:
    """Serialize a Schema for inclusion in a tool's JSON envelope."""
    return dataclass_to_jsonable_dict(s)
