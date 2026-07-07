"""Canonical registry of IVOA archives the server has first-class knowledge of.

This is the single source of truth for:

- Endpoint URLs surfaced in tool schemas (`Field(examples=...)`)
- Host substrings used by `_archive_label._STATIC_MAP` (archive labels +
  SSRF allow-list for `vo_sia_fetch`)
- Test fixtures (instead of duplicating URL strings)

Archives not listed here still work zero-touch via `vo_registry_search` —
this module is just for the well-known ones we want the LLM to see in
the tool schemas and operators to see labeled in responses.

To add a new archive: add one `Archive(...)` entry to `KNOWN_ARCHIVES`.
No other file needs to be touched. Derived structures (the substring
map, schema examples, allow-list) update automatically.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Archive:
    """Static facts about an IVOA archive.

    Fields are best-effort — most archives don't expose every protocol.
    `tap_url` / `sia_url` / `scs_url` are None when the archive doesn't
    have one we want to surface.

    `usage_notes` is a tuple of short, agent-facing strings capturing
    archive-specific gotchas — non-standard table locations, sync-vs-async
    routing recommendations, ADQL quirks, target-name conventions. These
    are surfaced to the LLM via the `vo_archive_list` tool and are the
    early scaffolding for what will eventually become a richer knowledge
    layer.
    """

    short_name: str
    display_name: str
    host_substrings: tuple[str, ...]
    tap_url: str | None = None
    sia_url: str | None = None
    scs_url: str | None = None
    waveband: str | None = None
    description: str = ""
    notable_tables: tuple[str, ...] = field(default_factory=tuple)
    usage_notes: tuple[str, ...] = field(default_factory=tuple)


KNOWN_ARCHIVES: tuple[Archive, ...] = (
    # Declaration order is load-bearing: the first TAP-having entries are the
    # endpoint examples surfaced in tool schemas (see tap_endpoint_description).
    # Keep the archives we most want the LLM to reach for at the top.
    Archive(
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
            "access_url values are on-the-fly cutout links (/svc/cutout?...), "
            "fetchable with vo_sia_fetch.",
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
    ),
    Archive(
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
            "Spatial filters work directly in sync — no need to avoid them. "
            "Two forms: INTERSECTS(CIRCLE('ICRS', ra, dec, r), s_region) = 1 "
            "matches the actual observed field footprint (mosaics included) "
            "and is the form ALMA's own example queries use; "
            "CONTAINS(POINT('ICRS', s_ra, s_dec), CIRCLE('ICRS', ra, dec, r)) "
            "= 1 matches only the pointing centre. Prefer INTERSECTS against "
            "s_region for completeness.",
            "Sync is fine for spatially- or proposal-filtered queries. "
            "Unfiltered full-table scans and aggregates (e.g. SELECT DISTINCT "
            "<col> or GROUP BY <col> with no WHERE) time out on /sync against "
            "this large table — run those with mode='async' (or 'auto', which "
            "auto-promotes on timeout).",
            "Rows are at spectral-window x execution granularity: one Member "
            "OUS yields many rows (one per spectral window per execution "
            "block). member_ous_uid is the canonical key for a downloadable "
            "dataset — use SELECT DISTINCT member_ous_uid to collapse to "
            "distinct datasets. Do NOT GROUP BY t_min: a single OUS spans "
            "multiple executions with different t_min.",
            "Every observation also carries calibration scans. Filter "
            "science_observation = 'T' to drop pointing/calibration rows, and "
            "qa2_passed = 'T' to keep only data that passed Quality Assurance "
            "2 (both are 'T'/'F' char flags, not booleans).",
            "target_name often holds a calibrator/source designation (e.g. "
            "'J1325-4301'), not a popular source name. Match cross-archive by "
            "POSITION (cone on s_ra/s_dec or INTERSECTS on s_region), not by "
            "target_name. A separate sourcecatalogue.source_cone_search view "
            "exposes measured calibrator fluxes.",
            "The obscore view is enriched for literature/PI discovery: "
            "obs_creator_name and pi_name (PI, case-insensitive partial "
            "match), proposal_authors, first_author / authors / pub_title / "
            "pub_abstract / publication_year / bib_reference (refereed "
            "publications), and proposal_abstract. These support 'find the "
            "ALMA data behind paper X' or 'data with PI Y' directly in ADQL.",
            "data_rights is 'Public' or 'Proprietary'. Proprietary datasets "
            "(still inside their proprietary period) are listed but not "
            "downloadable; obs_release_date is the public-availability "
            "timestamp.",
            "Beyond TAP, ALMA exposes a SIAv2 service "
            "(https://almascience.nrao.edu/sia2) for positional image "
            "discovery. It returns the same extended-ObsCore columns as the "
            "TAP view, so the obscore filtering knowledge applies. Use "
            "vo_sia_search for 'what ALMA images cover this position' without "
            "writing ADQL.",
            "Downloads go through DataLink, not direct file links. access_url "
            "on both obscore and SIA rows points at "
            "https://almascience.org/datalink/sync?ID=<member_ous_uid>, which "
            "returns a VOTable of the actual files to fetch (follow the "
            "indirection, as with CADC). Don't rely on access_format to detect "
            "this — ALMA truncates it to 9 chars ('applicati').",
            "The sourcecatalogue.source_cone_search table is a calibrator / "
            "source flux catalogue (m_ra, m_dec, m_frequency in Hz, m_flux in "
            "Jy, band_name — including 'non-ALMA Band' entries), separate from "
            "the obscore observation view. Filter it spatially on m_ra/m_dec; "
            "its s_ra_deg/s_dec_deg can be NULL, so CONTAINS on those throws "
            "an Oracle SDO_GEOMETRY error.",
            "Mirrored at almascience.nrao.edu (NA), almascience.eso.org (EU), "
            "and almascience.nao.ac.jp (EA). All three serve identical data, "
            "over TAP, SIAv2, and DataLink alike.",
        ),
    ),
    Archive(
        short_name="nrao",
        display_name="NRAO Science Data Archive",
        # Multiple historical hostnames for the NRAO archive web/query
        # interfaces. `almascience.nrao.edu` is intentionally NOT listed
        # here — that traffic is labeled "alma" via the entry below.
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
    ),
    Archive(
        short_name="eso",
        display_name="ESO Science Archive",
        host_substrings=("archive.eso",),
        tap_url="https://archive.eso.org/tap_obs",
        waveband="optical",
        description="European Southern Observatory archive (VLT, La Silla).",
        notable_tables=("ivoa.ObsCore",),
    ),
    Archive(
        short_name="cadc",
        display_name="Canadian Astronomy Data Centre",
        host_substrings=("cadc-ccda.hia-iha", "ws.cadc-ccda"),
        tap_url="https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/tap",
        sia_url="https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/sia",
        waveband="multi",
        description=("Multi-mission archive — TESS, JWST, CFHT, HST imaging available via SIA2."),
        usage_notes=(
            "SIA2 results' `access_url` column points at a DataLink VOTable, "
            "NOT directly at the FITS file. Check `access_format` — if it "
            "contains `content=datalink`, you must follow the indirection.",
            "Datalink follow-through recipe (verified live): "
            "(1) GET the access_url with Accept: application/x-votable+xml; "
            "(2) parse the VOTable rows; "
            "(3) find the row where semantics == '#this' — that's the "
            "primary image; "
            "(4) GET its access_url to get the real FITS bytes "
            "(the destination may be on a different host like "
            "mast.stsci.edu or S3 — follow redirects).",
            "Use `obs_collection` to filter by mission: 'TESS', 'JWST', 'CFHT', 'HST', etc.",
        ),
    ),
    Archive(
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
    ),
    Archive(
        short_name="gaia_ari",
        display_name="Gaia ARI Heidelberg",
        host_substrings=("gaia.ari.uni-heidelberg.de",),
        scs_url="https://gaia.ari.uni-heidelberg.de/cone/gaiadr2?",
        waveband="optical",
        description=(
            "Heidelberg's Gaia mirror — exposes a Simple Cone Search endpoint for legacy clients."
        ),
    ),
    Archive(
        short_name="sdss",
        display_name="Sloan Digital Sky Survey",
        host_substrings=("sdss.org",),
        waveband="optical",
        description="SDSS imaging and spectroscopic archive.",
    ),
)


# ---------- derived lookups ----------


def by_short_name(name: str) -> Archive | None:
    """Return the archive with the given short_name, or None."""
    for a in KNOWN_ARCHIVES:
        if a.short_name == name:
            return a
    return None


def host_substring_to_short_name() -> dict[str, str]:
    """Flatten host_substrings tuple into a substring → short_name map.

    Used by `_archive_label._STATIC_MAP`. Archives with multiple
    host substrings (e.g. CADC's two) contribute multiple entries
    mapping to the same short_name.
    """
    return {
        sub: archive.short_name for archive in KNOWN_ARCHIVES for sub in archive.host_substrings
    }


def tap_endpoint_urls() -> list[str]:
    """All TAP URLs we know about, in declaration order."""
    return [a.tap_url for a in KNOWN_ARCHIVES if a.tap_url]


def sia_endpoint_urls() -> list[str]:
    """All SIA URLs we know about, in declaration order."""
    return [a.sia_url for a in KNOWN_ARCHIVES if a.sia_url]


def scs_endpoint_urls() -> list[str]:
    """All SCS URLs we know about, in declaration order."""
    return [a.scs_url for a in KNOWN_ARCHIVES if a.scs_url]


# ---------- description helpers (used by tool Field descriptions) ----------


def _format_examples(archives: list[Archive], protocol: str) -> str:
    """Render a few example URLs inline for a tool's Field description.

    Used to keep the LLM-facing schema in sync with the canonical list
    without having to duplicate "'<url>' (<display_name>)" pairs by hand.
    """
    parts = []
    for a in archives:
        url = getattr(a, f"{protocol}_url")
        if url:
            parts.append(f"'{url}' ({a.display_name})")
    return " or ".join(parts)


def tap_endpoint_description() -> str:
    """The full description string for a TAP endpoint parameter."""
    primary = [a for a in KNOWN_ARCHIVES if a.tap_url][:2]
    return (
        f"Full TAP service URL. Example: {_format_examples(primary, 'tap')}. "
        "Discover other services via vo_registry_search."
    )


def sia_endpoint_description() -> str:
    """The full description string for a SIA endpoint parameter."""
    primary = [a for a in KNOWN_ARCHIVES if a.sia_url][:2]
    examples_text = _format_examples(primary, "sia")
    return (
        f"SIA endpoint URL — SIA 2.0 or 1.0. Example: {examples_text}. "
        "vo_sia_search auto-detects the version (SIA2, falling back to SIA1 "
        "as used by NOIRLab Data Lab); pass the version argument to force one. "
        "Discover endpoints with vo_registry_search(servicetype='sia')."
    )


def scs_endpoint_description() -> str:
    """The full description string for a SCS endpoint parameter."""
    primary = [a for a in KNOWN_ARCHIVES if a.scs_url][:2]
    return (
        f"Simple Cone Search endpoint URL. Example: {_format_examples(primary, 'scs')}. "
        "Prefer vo_tap_query for archives that expose a TAP endpoint — "
        "vo_cone_search is here for SCS-only legacy services."
    )
