"""NRAO Science Data Archive."""

from astro_archives_mcp.archives._model import Archive, Schema

ARCHIVE = Archive(
    short_name="nrao",
    display_name="NRAO Science Data Archive",
    # Multiple historical hostnames for the NRAO archive web/query
    # interfaces. `almascience.nrao.edu` is intentionally NOT listed
    # here — that traffic is labeled "alma" via the alma archive.
    host_substrings=("data.nrao", "data-query.nrao", "archive.nrao"),
    # TAP service per NRAO scripted-access docs:
    # https://science.nrao.edu/facilities/vla/archive/scripted-access-to-the-nrao-archive
    # Note: obscore table lives under `tap_schema.obscore`, not the
    # standard `ivoa.obscore` location used by ALMA/ESO.
    tap_url="https://data-query.nrao.edu/tap",
    waveband="radio",
    description=(
        "NRAO's unified data archive — serves VLA (historical + Karl G. "
        "Jansky VLA), VLBA, GMVA, and GBT (2014–2020) observations, "
        "plus mirrors ALMA archival products. Radio interferometric "
        "and single-dish data. ObsCore-style metadata table at "
        "tap_schema.obscore (NRAO uses a non-standard location for it)."
    ),
    notable_tables=("tap_schema.obscore",),
    usage_notes=(
        "USE mode='async' FOR ALL DATA QUERIES. The /sync TAP endpoint "
        "returns 5xx errors on reads against tap_schema.obscore — even "
        "for trivial `SELECT TOP 1 *`. Metadata queries against "
        "tap_schema.tables, tap_schema.columns work fine in sync.",
        "ObsCore is at `tap_schema.obscore`, NOT the standard "
        "`ivoa.obscore`. Queries against `ivoa.obscore` will fail.",
        "Even in async mode, queries that lack a spatial predicate "
        "tend to error out. ALWAYS include a CIRCLE/CONTAINS positional "
        "filter on (s_ra, s_dec). Trivial SELECT DISTINCT or full-table "
        "scans typically fail.",
        "ADQL string functions LOWER() and UPPER() FAIL on NRAO (spec "
        "violation). Use exact-case equality (`instrument_name = 'GBT'`) "
        "or LIKE patterns. Enumerated case-sensitive values you'll need: "
        "instrument_name ∈ {'EVLA', 'VLA', 'VLBA', 'GBT'}, "
        "facility_name = 'NRAO' (uniformly — not the instrument).",
        "The ObsCore standard column `dataproduct_subtype` is ABSENT "
        "from NRAO's tap_schema.obscore. Don't reference it. The 41 "
        "available columns are: standard ObsCore (minus subtype) plus "
        "extensions (project_code, configuration, num_antennas, "
        "max_uv_dist, spw_names, center_frequencies, bandwidths, "
        "nums_channels, spectral_resolutions, aggregate_bandwidth, "
        "scan_num, proprietary_status, qa_notes).",
        "On phase=ERROR the UWS `error_summary` field is always empty "
        "— no diagnostic message. Avoid speculating about what went "
        "wrong; instead, isolate the offending clause by simplifying "
        "the query and re-submitting. Common ERROR triggers: missing "
        "spatial predicate, LOWER/UPPER in WHERE, non-existent column.",
        "Rows are scan-level, not execution-block-level. For "
        "per-observation summaries, GROUP BY project_code (e.g. "
        "'13B-088', 'VLASS3.2') or obs_publisher_did.",
        "VLASS `target_name` uses J2000 sexagesimal packed designation "
        "(e.g. '1239540+023112' = RA 12h39m54.0s, Dec +02°31'12\"), NOT "
        "source names like '3C 273'. Plain VLA observations use "
        "proposer-supplied target strings. ALWAYS match cross-archive by "
        "POSITION, not by target_name.",
        "Common radio sources are stored under their radio designations, "
        "not optical/popular names: Hydra-A → '3C218'; M87 → '3C274'; "
        "Cygnus A → '3C405'; Centaurus A → 'NGC5128'. ALMA uses "
        "calibrator names like 'J1229+0203' (3C 273). If a target_name "
        "search returns nothing, prefer cone-search by position.",
        "ADQL aggregate support is partial. COUNT(DISTINCT ...) with "
        "CASE WHEN sometimes fails server-side. Prefer simpler aggregates "
        "(plain COUNT, MIN/MAX, GROUP BY) and assemble multi-aggregate "
        "results client-side.",
        "The `freq_min/freq_max` extension columns (in Hz) disagree "
        "with `em_min/em_max` (standard ObsCore, in meters) by ~1% on "
        "the same row. Don't trust either to better than that precision "
        "without checking the spectral_resolutions column.",
        "VLA-specific extension columns beyond standard ObsCore: "
        "array configuration (A/B/C/D + hybrids), project code, antenna "
        "count, spectral-window setup. Inspect columns via "
        "vo_registry_describe.",
        "VOSI endpoints are partially implemented. /availability and "
        "/tables return valid VOSI XML, but /capabilities is a hard 404 "
        "(raw Tomcat HTML). ObsCore-by-datamodel discovery is impossible "
        "because no capability document declares the data model. Always "
        "validate Content-Type is text/xml before trusting any VOSI body.",
    ),
    schemas=(
        Schema(
            archive="nrao",
            table="tap_schema.obscore",
            missing_standard_columns=("dataproduct_subtype",),
            value_enums={
                "instrument_name": ("EVLA", "VLA", "VLBA", "GBT"),
                "facility_name": ("NRAO",),
            },
        ),
    ),
    priority=30,
)
