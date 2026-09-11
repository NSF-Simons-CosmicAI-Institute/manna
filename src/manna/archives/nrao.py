"""NRAO Science Data Archive."""

from manna.archives._audit import Audit
from manna.archives._count import ContainsPoint, CountTarget
from manna.archives._model import Archive, Note, Pitfall, Schema

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
            id="async-or-auto-for-data",
            text=(
                "Use mode='auto' (or mode='async') for DATA queries against "
                "tap_schema.obscore. Sync reads are unreliable here: unfiltered or "
                "heavy reads always fail, and even spatially-filtered reads are "
                "load-dependent — they can return in seconds or blow past the sync "
                "timeout. mode='auto' tries sync first and promotes to async on a "
                "timeout, so it is the safe default; mode='async' is always safe."
            ),
            audit=Audit.manual(
                "Which mode succeeds is load-dependent, so no single probe settles "
                "it: filtered sync reads returned rows in ~3s on 2026-07-16 but were "
                "pure read-timeouts the evening before. The deterministic half — "
                "unfiltered reads never succeeding — is probed by "
                "sync-unfiltered-reads-fail."
            ),
        ),
        Note(
            id="sync-unfiltered-reads-fail",
            text=(
                "Unfiltered reads against tap_schema.obscore FAIL in sync — even a "
                "trivial `SELECT TOP 1 *`. The failure is NOT a clean 5xx: /sync "
                "returns HTTP 200 with a VOTable carrying QUERY_STATUS='ERROR' after "
                "~50-60s, or the read simply times out. Spatially-filtered reads "
                "(CONTAINS/CIRCLE on s_ra, s_dec) DO complete in sync when the server "
                "is responsive, but are load-dependent — prefer mode='auto'. Metadata "
                "queries against tap_schema.tables / tap_schema.columns are fast and "
                "reliable in sync."
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
            # that never reveals where obscore actually lives — so prevention
            # (an up-front note, no triggers) is the only channel that helps.
            pitfall=Pitfall(
                guidance="obscore is at tap_schema.obscore, NOT ivoa.obscore (which does not exist).",
            ),
        ),
        Note(
            id="unfiltered-scans-fail",
            text=(
                "Unfiltered scans of tap_schema.obscore fail even in async: a bare "
                "SELECT COUNT(*) or SELECT DISTINCT over the whole table ends in "
                "phase=ERROR after ~30 min. Any selective WHERE works, spatial or "
                "not — non-spatial filters such as instrument_name = 'GBT' or "
                "project_code = 'VLASS3.2' complete async (2–12 min under load); a "
                "CIRCLE/CONTAINS cone on (s_ra, s_dec) is the fastest path. Prefer a "
                "cone when the question is positional, but do not add fake geometry "
                "to a non-positional query."
            ),
            audit=Audit.manual(
                "The failing case takes ~30 min to reach ERROR and the passing cases "
                "2–12 min, so neither is a viable audit probe. Verified live "
                "2026-09-10: instrument_name/project_code/BETWEEN filters all "
                "COMPLETED async; unfiltered COUNT(*) reached ERROR after 1,895 s. "
                "(Replaced the earlier 'spatial-predicate-required' note, which "
                "was wrong.)"
            ),
        ),
        Note(
            id="lower-upper-fail",
            text=(
                "NRAO's ADQL has no string functions: LOWER(), UPPER() and ILIKE are "
                "rejected ('Function [LOWER] is not found in TapSchema'), and the "
                "string concatenation operator || fails with a bare parser error. "
                "Use exact-case equality (`instrument_name = 'GBT'`) or LIKE "
                "patterns, and do string assembly client-side. (LOWER/UPPER/ILIKE "
                "are an optional ADQL 2.1 feature; NRAO cannot declare that because "
                "its /capabilities endpoint is missing.)"
            ),
            audit=Audit.probe(
                expect="error",
                adql=(
                    "SELECT TOP 1 table_name FROM tap_schema.tables "
                    "WHERE LOWER(table_name) = 'tap_schema.obscore'"
                ),
            ),
            # The pitfall issue #57 is named after: true, probed, and served by
            # list_archives — and the model wrote LOWER() anyway, in BOTH eval
            # conditions. It throws, so the fix rides the error hint rather than
            # the description budget (an error hint: triggers decide when it fires).
            pitfall=Pitfall(
                guidance=(
                    "NRAO's TAP rejects the ADQL string functions LOWER()/UPPER()/ILIKE "
                    "and the || concatenation operator. Re-run without them: match exact "
                    "case (instrument_name = 'GBT') or use a LIKE pattern."
                ),
                triggers=("LOWER(", "UPPER(", "ILIKE", "||"),
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
        # A note claiming "UWS error_summary is always empty on ERROR" lived here
        # until 2026-09-10. It was our bug, not NRAO's: the tools read
        # `job.error_summary`, an attribute pyvo never had, so every archive's
        # message was dropped. NRAO does populate errorSummary/message — see
        # backends/tap.py::job_error_message and tests/archives/test_nrao.py.
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
                "spectral-window setup. Inspect columns via describe_ivoa_service."
            ),
            audit=Audit.manual(
                "General pointer to describe_ivoa_service for column introspection "
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
            # Live GROUP BY instrument_name, facility_name on a 0.5° cone around
            # 3C 273, 2026-09-10 (scan rows): EVLA 789k, VLBA 63k, ALMA 49k,
            # VLA 47k, GMVA 44k, GBT 2.8k. ALMA rows carry facility_name='ALMA';
            # everything else 'NRAO'.
            value_enums={
                "instrument_name": ("EVLA", "VLA", "VLBA", "GBT", "GMVA", "ALMA"),
                "facility_name": ("NRAO", "ALMA"),
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
                        "instrument_name ∈ {'EVLA', 'VLA', 'VLBA', 'GBT', 'GMVA', "
                        "'ALMA'}; facility_name is 'NRAO' for all of those except the "
                        "ALMA rows, which carry facility_name = 'ALMA'. Yes, this "
                        "table includes ALMA scans (NRAO mirrors them) — for ALMA "
                        "science prefer the ALMA archive's own richer ivoa.obscore."
                    ),
                    audit=Audit.count(
                        table="tap_schema.obscore",
                        columns=("instrument_name", "facility_name"),
                    ),
                ),
                Note(
                    id="obs-collection-sparse",
                    text=(
                        "obs_collection is empty on almost every row; the only "
                        "populated values seen are 'VLASS' and 'RealFast', and even "
                        "most VLASS scans leave it blank. Select VLASS by "
                        "project_code (LIKE 'VLASS%' or = 'VLASS3.2'), never by "
                        "obs_collection."
                    ),
                    audit=Audit.manual(
                        "Value-sparsity claim needs an async GROUP BY over obscore "
                        "(minutes); observed 2026-09-10 on a 0.5° cone: 1 VLASS + 15 "
                        "RealFast rows populated out of ~1.0M."
                    ),
                ),
                Note(
                    id="access-format-not-mime",
                    text=(
                        "access_format holds the literal 'Execution Block', not a MIME "
                        "type, so you cannot branch on it to detect DataLink the way "
                        "you can at ALMA/CADC. There is no scripted download path at "
                        "NRAO: hand the user the execution block id / access_url for "
                        "the web Archive Access Tool."
                    ),
                    audit=Audit.manual(
                        "Reading access_format requires an obscore row read, which is "
                        "async-only and load-dependent; observed 'Execution Block' on "
                        "every sampled row 2026-09-10 (candidate finding N-09)."
                    ),
                ),
            ),
        ),
    ),
    count_target=CountTarget(
        table="tap_schema.obscore",
        geometry=ContainsPoint("s_ra", "s_dec"),
        count_expr="COUNT(*)",
        mode="async",
    ),
    priority=30,
)
