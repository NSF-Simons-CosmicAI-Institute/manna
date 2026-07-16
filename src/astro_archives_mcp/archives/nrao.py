"""NRAO Science Data Archive."""

from astro_archives_mcp.archives._audit import Audit
from astro_archives_mcp.archives._model import Archive, Note, Schema, Trap

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
        Note(
            id="async-required-all-data",
            text="USE mode='async' for all DATA queries against tap_schema.obscore.",
            audit=Audit.manual(
                "All DATA queries must use mode='async' (sync 5xxs on obscore reads)."
            ),
        ),
        Note(
            id="sync-5xx-on-obscore",
            text=(
                "The /sync TAP endpoint returns 5xx errors on reads against "
                "tap_schema.obscore — even for trivial `SELECT TOP 1 *`. Metadata "
                "queries against tap_schema.tables, tap_schema.columns work fine in "
                "sync."
            ),
            audit=Audit.probe(expect="error", adql="SELECT TOP 1 * FROM tap_schema.obscore"),
        ),
        Note(
            id="obscore-ivoa-absent",
            text=(
                "ObsCore is NOT at the standard `ivoa.obscore` — that table is "
                "absent, so queries against it will fail."
            ),
            audit=Audit.probe(
                expect="empty",
                adql="SELECT table_name FROM tap_schema.tables WHERE table_name = 'ivoa.obscore'",
            ),
        ),
        Note(
            id="obscore-at-tap-schema",
            text="ObsCore lives at the non-standard `tap_schema.obscore`, not the standard location.",
            audit=Audit.probe(
                expect="nonempty",
                adql=(
                    "SELECT table_name FROM tap_schema.tables "
                    "WHERE table_name = 'tap_schema.obscore'"
                ),
            ),
            # Querying ivoa.obscore here errors, but with a bare "table not found"
            # that never reveals where obscore actually lives — so prevention is
            # the only channel that helps.
            trap=Trap(
                kind="silent",
                guidance="obscore is at tap_schema.obscore, NOT ivoa.obscore (which does not exist).",
            ),
        ),
        Note(
            id="spatial-predicate-required",
            text=(
                "Even in async mode, queries that lack a spatial predicate tend to "
                "error out. ALWAYS include a CIRCLE/CONTAINS positional filter on "
                "(s_ra, s_dec). Trivial SELECT DISTINCT or full-table scans typically "
                "fail."
            ),
            audit=Audit.manual(
                "Even in async, queries lacking a CIRCLE/CONTAINS spatial predicate "
                "tend to error — depends on server load/query shape, not a single "
                "deterministic probe."
            ),
        ),
        Note(
            id="lower-upper-fail",
            text=(
                "ADQL string functions LOWER() and UPPER() FAIL on NRAO (spec "
                "violation). Use exact-case equality (`instrument_name = 'GBT'`) or "
                "LIKE patterns instead."
            ),
            audit=Audit.probe(
                expect="error",
                adql=(
                    "SELECT TOP 1 table_name FROM tap_schema.tables "
                    "WHERE LOWER(table_name) = 'tap_schema.obscore'"
                ),
            ),
            # The trap issue #57 is named after: true, probed, and served by
            # vo_archive_list — and the model wrote LOWER() anyway, in BOTH eval
            # conditions. It throws, so the fix rides the error hint rather than
            # the description budget.
            trap=Trap(
                kind="loud",
                guidance=(
                    "NRAO's TAP rejects the ADQL string functions LOWER() and UPPER(). "
                    "Re-run without them: match exact case (instrument_name = 'GBT') or "
                    "use a LIKE pattern."
                ),
                triggers=("LOWER(", "UPPER("),
            ),
        ),
        Note(
            id="obscore-extension-columns",
            text=(
                "The 41 available columns on tap_schema.obscore are: standard "
                "ObsCore (minus dataproduct_subtype) plus extensions (project_code, "
                "configuration, num_antennas, max_uv_dist, spw_names, "
                "center_frequencies, bandwidths, nums_channels, "
                "spectral_resolutions, aggregate_bandwidth, scan_num, "
                "proprietary_status, qa_notes)."
            ),
            audit=Audit.count(
                table="tap_schema.obscore",
                columns=(
                    "project_code",
                    "configuration",
                    "num_antennas",
                    "max_uv_dist",
                    "spw_names",
                    "center_frequencies",
                    "bandwidths",
                    "nums_channels",
                    "spectral_resolutions",
                    "aggregate_bandwidth",
                    "scan_num",
                    "proprietary_status",
                    "qa_notes",
                ),
            ),
        ),
        Note(
            id="error-summary-empty",
            text=(
                "On phase=ERROR the UWS `error_summary` field is always empty — no "
                "diagnostic message. Avoid speculating about what went wrong; "
                "instead, isolate the offending clause by simplifying the query and "
                "re-submitting. Common ERROR triggers: missing spatial predicate, "
                "LOWER/UPPER in WHERE, non-existent column."
            ),
            audit=Audit.manual(
                "On phase=ERROR the UWS error_summary is always empty (no "
                "diagnostic) — nothing to assert against live beyond the control "
                "probe."
            ),
        ),
        Note(
            id="rows-scan-level",
            text=(
                "Rows are scan-level, not execution-block-level. For "
                "per-observation summaries, GROUP BY project_code (e.g. "
                "'13B-088', 'VLASS3.2') or obs_publisher_did."
            ),
            audit=Audit.manual(
                "Row-granularity claim — a structural fact about the data model, "
                "not a single falsifiable probe."
            ),
        ),
        Note(
            id="vlass-target-name-packed",
            text=(
                "VLASS `target_name` uses J2000 sexagesimal packed designation "
                "(e.g. '1239540+023112' = RA 12h39m54.0s, Dec +02°31'12\"), NOT "
                "source names like '3C 273'. Plain VLA observations use "
                "proposer-supplied target strings. ALWAYS match cross-archive by "
                "POSITION, not by target_name."
            ),
            audit=Audit.manual(
                "VLASS target_name packing convention over many rows — not a "
                "single deterministic probe."
            ),
        ),
        Note(
            id="radio-designations",
            text=(
                "Common radio sources are stored under their radio designations, "
                "not optical/popular names: Hydra-A → '3C218'; M87 → '3C274'; "
                "Cygnus A → '3C405'; Centaurus A → 'NGC5128'. ALMA uses "
                "calibrator names like 'J1229+0203' (3C 273). If a target_name "
                "search returns nothing, prefer cone-search by position."
            ),
            audit=Audit.manual(
                "Naming-convention advisory over many rows — not a single deterministic probe."
            ),
        ),
        Note(
            id="aggregate-partial",
            text=(
                "ADQL aggregate support is partial. COUNT(DISTINCT ...) with "
                "CASE WHEN sometimes fails server-side. Prefer simpler aggregates "
                "(plain COUNT, MIN/MAX, GROUP BY) and assemble multi-aggregate "
                "results client-side."
            ),
            audit=Audit.manual(
                "ADQL aggregate support is partial — COUNT(DISTINCT ...) with "
                "CASE WHEN can fail server-side; depends on query shape, not "
                "deterministically probeable with one ADQL statement."
            ),
        ),
        Note(
            id="freq-extension-columns",
            text="The `freq_min`/`freq_max` extension columns (in Hz) exist on tap_schema.obscore.",
            audit=Audit.count(table="tap_schema.obscore", columns=("freq_min", "freq_max")),
        ),
        Note(
            id="freq-em-disagreement",
            text=(
                "The `freq_min`/`freq_max` extension columns (in Hz) disagree with "
                "`em_min`/`em_max` (standard ObsCore, in meters) by ~1% on the same "
                "row. Don't trust either to better than that precision without "
                "checking the spectral_resolutions column."
            ),
            audit=Audit.manual(
                "freq_min/freq_max (Hz) vs em_min/em_max (m) disagreement is a "
                "per-row data-quality drift, not a single deterministic probe."
            ),
        ),
        Note(
            id="vla-extension-columns-advisory",
            text=(
                "VLA-specific extension columns beyond standard ObsCore: array "
                "configuration (A/B/C/D + hybrids), project code, antenna count, "
                "spectral-window setup. Inspect columns via vo_registry_describe."
            ),
            audit=Audit.manual(
                "General pointer to vo_registry_describe for column introspection "
                "— already covered structurally by the obscore-extension-columns "
                "count probe; the advisory framing itself isn't separately "
                "falsifiable."
            ),
        ),
        Note(
            id="vosi-capabilities-404",
            text=(
                "VOSI endpoints are partially implemented. `/availability` and "
                "`/tables` return valid VOSI XML, but `/capabilities` is a hard "
                "404 (raw Tomcat HTML). ObsCore-by-datamodel discovery is "
                "impossible because no capability document declares the data "
                "model. Always validate Content-Type is text/xml before trusting "
                "any VOSI body."
            ),
            audit=Audit.manual(
                "VOSI partially implemented: /availability and /tables OK, "
                "/capabilities is a hard 404."
            ),
        ),
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
            notes=(
                Note(
                    id="no-dataproduct-subtype",
                    text=(
                        "The ObsCore standard column `dataproduct_subtype` is "
                        "ABSENT from NRAO's tap_schema.obscore. Don't reference it."
                    ),
                    audit=Audit.probe(
                        expect="empty",
                        adql=(
                            "SELECT column_name FROM tap_schema.columns "
                            "WHERE table_name = 'tap_schema.obscore' "
                            "AND column_name = 'dataproduct_subtype'"
                        ),
                    ),
                ),
                Note(
                    id="instrument-facility-columns",
                    text=(
                        "Enumerated case-sensitive values you'll need: "
                        "instrument_name ∈ {'EVLA', 'VLA', 'VLBA', 'GBT'}, "
                        "facility_name = 'NRAO' (uniformly — not the instrument)."
                    ),
                    audit=Audit.count(
                        table="tap_schema.obscore",
                        columns=("instrument_name", "facility_name"),
                    ),
                ),
            ),
        ),
    ),
    priority=30,
)
