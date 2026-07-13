"""ALMA Science Archive."""

from astro_archives_mcp.archives._audit import Audit
from astro_archives_mcp.archives._model import Archive, Note, Schema

ARCHIVE = Archive(
    short_name="alma",
    display_name="ALMA Science Archive",
    host_substrings=("almascience",),
    tap_url="https://almascience.nrao.edu/tap",
    sia_url="https://almascience.nrao.edu/sia2",
    waveband="millimeter",
    description=(
        "Millimeter/submillimeter interferometric data from ALMA, served "
        "as an extended ObsCore 1.1 view (ivoa.obscore) with ALMA-specific "
        "columns (proposal/PI metadata, receiver bands, QA flags, "
        "sensitivities) and bibliography links to refereed publications. "
        "Also exposes a SIAv2 image-discovery service and a DataLink "
        "download service. Mirrored at NRAO (NA), ESO (EU), and NAOJ (EA)."
    ),
    notable_tables=("ivoa.obscore", "sourcecatalogue.source_cone_search"),
    usage_notes=(
        Note(
            id="sync-spatial-ok",
            text=(
                "Spatial filters work directly in /sync — no need to avoid them or "
                "promote to async. INTERSECTS(CIRCLE('ICRS', ra, dec, r), s_region) = 1 "
                "matches the actual observed field footprint (mosaics included) and is "
                "the form ALMA's own example queries use."
            ),
            audit=Audit.probe(
                expect="ok",
                adql=(
                    "SELECT TOP 1 s_ra, s_dec FROM ivoa.obscore "
                    "WHERE INTERSECTS(CIRCLE('ICRS', 201.365, -43.019, 0.05), s_region) = 1"
                ),
            ),
        ),
        Note(
            id="spatial-intersects-vs-contains",
            text=(
                "CONTAINS(POINT('ICRS', s_ra, s_dec), CIRCLE('ICRS', ra, dec, r)) = 1 "
                "matches only the pointing centre, not the full footprint — prefer "
                "INTERSECTS against s_region for completeness."
            ),
            audit=Audit.manual(
                "Advisory on which spatial predicate form to prefer; both work, so "
                "not independently falsifiable beyond the sync-spatial-ok probe."
            ),
        ),
        Note(
            id="unfiltered-scan-timeout",
            text=(
                "Unfiltered full-table scans and aggregates (e.g. SELECT DISTINCT "
                "<col> or GROUP BY <col> with no WHERE) time out on /sync against "
                "this large table — run those with mode='async' (or 'auto', which "
                "auto-promotes on timeout)."
            ),
            audit=Audit.manual(
                "Timeout-under-load behaviour — not deterministically probeable "
                "without risking a slow/flaky live scan."
            ),
        ),
        Note(
            id="granularity-key",
            text=(
                "Rows are at spectral-window x execution granularity: one Member "
                "OUS yields many rows (one per spectral window per execution "
                "block). member_ous_uid is the canonical key for a downloadable "
                "dataset — use SELECT DISTINCT member_ous_uid to collapse to "
                "distinct datasets. Do NOT GROUP BY t_min: a single OUS spans "
                "multiple executions with different t_min."
            ),
            audit=Audit.count(table="ivoa.obscore", columns=("member_ous_uid",)),
        ),
        Note(
            id="qa-flag-columns",
            text=(
                "Every observation also carries calibration scans. Filter "
                "science_observation = 'T' to drop pointing/calibration rows, and "
                "qa2_passed = 'T' to keep only data that passed Quality Assurance "
                "2 (both are 'T'/'F' char flags, not booleans)."
            ),
            audit=Audit.count(table="ivoa.obscore", columns=("science_observation", "qa2_passed")),
        ),
        Note(
            id="target-name-calibrator",
            text=(
                "target_name often holds a calibrator/source designation (e.g. "
                "'J1325-4301'), not a popular source name. Match cross-archive by "
                "POSITION (cone on s_ra/s_dec or INTERSECTS on s_region), not by "
                "target_name."
            ),
            audit=Audit.manual(
                "Naming-convention advisory over many rows — not a single deterministic probe."
            ),
        ),
        Note(
            id="literature-columns",
            text=(
                "The obscore view is enriched for literature/PI discovery: "
                "obs_creator_name and pi_name (PI, case-insensitive partial "
                "match), proposal_authors, first_author / authors / pub_title / "
                "pub_abstract / publication_year / bib_reference (refereed "
                "publications), and proposal_abstract. These support 'find the "
                "ALMA data behind paper X' or 'data with PI Y' directly in ADQL."
            ),
            audit=Audit.count(
                table="ivoa.obscore",
                columns=(
                    "obs_creator_name",
                    "pi_name",
                    "proposal_authors",
                    "first_author",
                    "authors",
                    "pub_title",
                    "pub_abstract",
                    "publication_year",
                    "bib_reference",
                    "proposal_abstract",
                ),
            ),
        ),
        Note(
            id="data-rights-columns",
            text=(
                "data_rights is 'Public' or 'Proprietary'. Proprietary datasets "
                "(still inside their proprietary period) are listed but not "
                "downloadable; obs_release_date is the public-availability "
                "timestamp."
            ),
            audit=Audit.count(table="ivoa.obscore", columns=("data_rights", "obs_release_date")),
        ),
        Note(
            id="siav2-service",
            text=(
                "Beyond TAP, ALMA exposes a SIAv2 service "
                "(https://almascience.nrao.edu/sia2) for positional image "
                "discovery. It returns the same extended-ObsCore columns as the "
                "TAP view, so the obscore filtering knowledge applies. Use "
                "vo_sia_search for 'what ALMA images cover this position' without "
                "writing ADQL."
            ),
            audit=Audit.manual(
                "Service-capability description — verify by exercising "
                "vo_sia_search, not a TAP probe."
            ),
        ),
        Note(
            id="datalink-downloads",
            text=(
                "Downloads go through DataLink, not direct file links. access_url "
                "on both obscore and SIA rows points at "
                "https://almascience.org/datalink/sync?ID=<member_ous_uid>, which "
                "returns a VOTable of the actual files to fetch (follow the "
                "indirection, as with CADC)."
            ),
            audit=Audit.manual(
                "DataLink download recipe — a multi-step client flow, not a single ADQL probe."
            ),
        ),
        Note(
            id="access-format-truncated",
            text=(
                "Don't rely on access_format to detect this — ALMA truncates it "
                "to 9 chars ('applicati')."
            ),
            audit=Audit.manual(
                "String-truncation quirk in a metadata column — would need "
                "per-row inspection, not worth a live probe."
            ),
        ),
        Note(
            id="mirrors",
            text=(
                "Mirrored at almascience.nrao.edu (NA), almascience.eso.org (EU), "
                "and almascience.nao.ac.jp (EA). All three serve identical data, "
                "over TAP, SIAv2, and DataLink alike."
            ),
            audit=Audit.manual(
                "Cross-site mirror-equivalence claim — would require querying "
                "three endpoints and diffing, out of scope for a single probe."
            ),
        ),
    ),
    schemas=(
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
                Note(
                    id="obscore-member-ous-granularity",
                    text=(
                        "member_ous_uid identifies a downloadable dataset (Member OUS). "
                        "Rows are finer than that — one per spectral window per execution "
                        "— so SELECT DISTINCT member_ous_uid is the way to count/collapse "
                        "to datasets."
                    ),
                    audit=Audit.manual(
                        "Same live check as alma usage_note granularity-key "
                        "(member_ous_uid column); advisory here."
                    ),
                ),
                Note(
                    id="spatial-columns",
                    text=(
                        "Two spatial columns: s_ra/s_dec is the pointing centre (a point); "
                        "s_region is the WKT footprint of the observed field. Use "
                        "INTERSECTS(CIRCLE(...), s_region) to catch mosaics and fields "
                        "whose centre lies outside a small search radius."
                    ),
                    audit=Audit.count(table="ivoa.obscore", columns=("s_ra", "s_dec", "s_region")),
                ),
                Note(
                    id="band-list-column",
                    text=(
                        "band_list is a space-separated list of ALMA receiver bands "
                        "present, e.g. '6' or '3 6 7'. Bands run 1, 3-10 (no band 2). "
                        "Beware LIKE '%1%' — it also matches band 10; match an exact token "
                        "(band_list = '6') or pad with delimiters."
                    ),
                    audit=Audit.count(table="ivoa.obscore", columns=("band_list",)),
                ),
                Note(
                    id="calib-level-column",
                    text=(
                        "calib_level: 2 = Member-OUS (per-execution) products, 3 = "
                        "Group-OUS (combined) products."
                    ),
                    audit=Audit.count(table="ivoa.obscore", columns=("calib_level",)),
                ),
                Note(
                    id="frequency-columns",
                    text=(
                        "frequency is the tuned sky reference frequency (GHz); "
                        "frequency_support holds the full per-spectral-window frequency "
                        "ranges. em_min/em_max are the standard ObsCore wavelengths (m)."
                    ),
                    audit=Audit.count(
                        table="ivoa.obscore",
                        columns=("frequency", "frequency_support", "em_min", "em_max"),
                    ),
                ),
                Note(
                    id="proposal-id-cycle-encoding",
                    text=(
                        "proposal_id (e.g. '2022.1.01515.S') encodes the observing Cycle "
                        "in its 'YYYY.N' prefix; there is no numeric cycle column, so "
                        "filter a Cycle with proposal_id LIKE '2022.1.%'. Mapping: "
                        "Cy6='2018.1', Cy7='2019.1' (+ '2019.2' ACA supplemental call), "
                        "Cy8='2021.1', Cy9='2022.1', Cy10='2023.1', Cy11='2024.1'. NOTE "
                        "the gap: there is NO '2020.1' (Cycle 8 was delayed by the COVID "
                        "shutdown), so never infer a Cycle from a linear year count."
                    ),
                    audit=Audit.manual(
                        "Cycle-to-proposal_id-prefix mapping is a curated lookup table, "
                        "not a single falsifiable ADQL probe."
                    ),
                ),
                Note(
                    id="antenna-arrays-array-type",
                    text=(
                        "antenna_arrays is a space-separated list of 'Jxxx:PAD' tokens "
                        "(one per antenna), NOT an array-type label. Derive the ALMA "
                        "array from the PAD prefixes: DA*/DV* = 12-m (main) array, "
                        "CM* = 7-m ACA, PM* = Total Power. e.g. 12-m -> antenna_arrays "
                        "LIKE '%DV%' OR LIKE '%DA%'; 7-m -> LIKE '%CM%'; TP -> "
                        "LIKE '%PM%'. The 12-m/7-m/TP components of one program are "
                        "separate rows, so a project can appear under several types."
                    ),
                    audit=Audit.manual(
                        "Encoding convention inside a free-text column — needs "
                        "row-level pattern inspection, not a single ADQL probe."
                    ),
                ),
                Note(
                    id="resolution-columns-units",
                    text=(
                        "s_resolution and spatial_resolution are the synthesized-beam "
                        "angular resolution in ARCSEC (usually equal); for a '<1 arcsec' "
                        "request use spatial_resolution < 1.0. spatial_scale_max is the "
                        "largest recoverable angular scale (arcsec); velocity_resolution "
                        "is in m/s."
                    ),
                    audit=Audit.manual(
                        "Column-unit documentation — descriptive, not independently falsifiable."
                    ),
                ),
                Note(
                    id="science-keyword-format",
                    text=(
                        "science_keyword is a ';'-delimited list from ALMA's controlled "
                        "keyword vocabulary (a row may carry several; a 'null' token "
                        "appears for an unused slot), so match with LIKE, e.g. "
                        "science_keyword LIKE '%Outflows%'. Two distinct outflow keywords "
                        "exist: 'Outflows, jets and ionized winds' (protostellar/ISM) vs "
                        "'Outflows, jets, feedback' (galaxy-scale). scientific_category "
                        "is the coarser, single-valued parent classification."
                    ),
                    audit=Audit.manual(
                        "Free-text delimited-list convention — needs sampling many "
                        "rows, not a single deterministic probe."
                    ),
                ),
                Note(
                    id="enum-columns",
                    text=(
                        "scientific_category (coarse single-valued classification) and "
                        "dataproduct_type ('cube' or 'image') are controlled-vocabulary "
                        "columns."
                    ),
                    audit=Audit.count(
                        table="ivoa.obscore",
                        columns=("scientific_category", "dataproduct_type"),
                    ),
                ),
                Note(
                    id="bibliography-in-obscore",
                    text=(
                        "Bibliography is IN this table: publication_year (int), "
                        "first_author, authors, pub_title, bib_reference. So 'recent "
                        "papers that used ALMA data on X' is answerable here directly "
                        "(filter science_keyword + ORDER BY publication_year DESC) with "
                        "no separate publications service; rows with no linked paper "
                        "carry NULL in these columns."
                    ),
                    audit=Audit.manual(
                        "Cross-column usage recipe already covered structurally by "
                        "literature-columns' existence probe; the 'directly queryable' "
                        "framing itself isn't separately falsifiable."
                    ),
                ),
            ),
            cross_refs=(("nrao", "tap_schema.obscore"),),
        ),
        Schema(
            archive="alma",
            table="sourcecatalogue.source_cone_search",
            notes=(
                Note(
                    id="sourcecatalogue-table",
                    text=(
                        "sourcecatalogue.source_cone_search is a separate calibrator / "
                        "source flux catalogue view, distinct from the obscore "
                        "observation view."
                    ),
                    audit=Audit.probe(
                        expect="nonempty",
                        adql=(
                            "SELECT table_name FROM tap_schema.tables "
                            "WHERE table_name = 'sourcecatalogue.source_cone_search'"
                        ),
                    ),
                ),
                Note(
                    id="sourcecat-columns",
                    text=(
                        "Columns: m_ra/m_dec (deg), m_frequency (Hz), m_flux (Jy), "
                        "band_name, source_names, catalogue_name."
                    ),
                    audit=Audit.count(
                        table="sourcecatalogue.source_cone_search",
                        columns=(
                            "m_ra",
                            "m_dec",
                            "m_frequency",
                            "m_flux",
                            "band_name",
                            "source_names",
                            "catalogue_name",
                        ),
                    ),
                ),
                Note(
                    id="sourcecat-null-geometry",
                    text=(
                        "Filter spatially on m_ra/m_dec. The s_ra_deg/s_dec_deg columns "
                        "can be NULL, so CONTAINS(POINT('ICRS', s_ra_deg, s_dec_deg), ...) "
                        "raises ORA-13032 (Invalid NULL SDO_GEOMETRY)."
                    ),
                    audit=Audit.manual(
                        "NULL-triggered backend error depends on hitting a NULL row — "
                        "not a stable deterministic probe without a known-NULL row."
                    ),
                ),
                Note(
                    id="sourcecat-non-alma-band",
                    text=(
                        "band_name includes 'non-ALMA Band' rows (e.g. VLBI catalogue "
                        "entries at 8.3/23 GHz) — filter band_name if you only want ALMA "
                        "receiver bands."
                    ),
                    audit=Audit.manual(
                        "Value-distribution claim over free-text band_name — kept "
                        "manual for consistency rather than a fragile single-row probe."
                    ),
                ),
            ),
            cross_refs=(("alma", "ivoa.obscore"),),
        ),
    ),
    priority=20,
)
