# MCP evaluation plan — NOIRLab + ALMA

Benchmark suites for exercising `astro-archives-mcp` end-to-end against the two
archives we care about: **NOIRLab Astro Data Lab** (catalog TAP + `q3c` + SIA)
and the **ALMA Science Archive** (`ivoa.obscore` observation metadata).

Source questions live in `nrao_vault/Astro Docs/Benchmarking Questions/`. This
doc reframes them for what the server actually exposes and adds a tiered ALMA
suite parallel to the existing 15 NOIRLab prompts.

---

## 1. Reframed viability analysis

The two archives are **different kinds of service**, so the suites test
different capabilities and are *not* interchangeable in depth:

| | NOIRLab Astro Data Lab | ALMA Science Archive |
|---|---|---|
| Archive type | **Catalog** (`nsc_dr2`, `des_dr1`, `gaia_dr3`, `ls_dr9`, `desi_dr1`, …) | **Observation-metadata** obscore (`ivoa.obscore`) |
| MCP surface exercised | TAP + `q3c` spatial + SIA cutouts; row-level science | TAP obscore **discovery** (does target/band/config/resolution/paper exist?) + datalink fetch |
| Question style in the source set | Uniform multi-step workflows w/ verified ADQL | Heterogeneous — mix of docs lookups, library how-tos, and real obscore queries |
| Server-side knowledge | Rich per-table `schema_kb` | `ivoa.obscore` entry, now augmented (this branch) |

**Key correction vs. first pass:** ALMA's obscore is richer than assumed. It
carries publication columns (`publication_year`, `first_author`, `pub_title`,
`bib_reference`), `science_keyword`, `antenna_arrays`, and `spatial_resolution`
— so several questions first judged "not viable" (recent-papers, array-type,
resolution cuts) are in fact answerable in one TAP query. All column semantics
below are verified live against `https://almascience.nrao.edu/tap` (2026-07).

### ALMA source-question triage (Adele's set)

- **🟢 Real obscore-discovery tests** → basis for the suite in §3: M83 Band 6;
  HH 212 Band 7 <1″; public-band count; Cycle-10-observed-the-Sun; Cycle-9
  array usage; 12CO/13CO/C18O co-observed; recent outflow papers.
- **🟡 Retrievable but cross-archive / client-heavy:** Perseus protostars in
  ALMA ∩ JWST (uses registered CADC SIA2); HUDF ALMA-contours-over-JWST
  (retrieval fine, overlay is agent-side plotting).
- **🔴 Don't test this server (docs / other tools):** ALMA configs & angular
  resolutions (reference knowledge); which CASA version (not an obscore
  column); "likely needed Bandwidth Switching" (not a queryable field);
  ALMiner / `astroquery.alma` / "generate the archive portal URL" (presuppose
  a specific external library or the web portal, not the MCP's TAP path).

Net: ~6 clean server tests, ~3 partial, the rest test other systems.

### NOIRLab — unchanged verdict

Strong fit. The 15 tiered prompts (see the source `NOIRLab Questions.md`,
"Suggested science-user prompts") are the gold standard: verified `q3c` ADQL,
graduated Tier 1→7, and each separates the MCP retrieval step from client-side
computation. Coverage caveats on the "only" 8: #4 (weak-lensing shear catalog
absent), #7 (needs JPL Horizons ephemeris); #6 fine via `desi_dr1.zpix`.

### Equivalence verdict

Not equivalent, on three axes: **capability tested** (catalog rows vs.
observation discovery — complementary), **test-design quality** (NOIRLab set is
uniform/verified; ALMA source set is a grab-bag), **server readiness** (now
levelled up by the `schema_kb` ALMA augmentation on this branch).

---

## 2. NOIRLab suite (reference)

Use the existing 15 tiered prompts verbatim as the primary NOIRLab suite; they
are already MCP-shaped and query-verified. Index:

1. Catalog discovery · 2. Cone-search count · 3. CMD · 4. Color cutout (SIA) ·
5. Star/galaxy + color-color · 6. PM+parallax WD selection · 7. Overdensity
matched filter · 8. HEALPix density map · 9. Stream via crossmatch (MATERIALIZED
CTE + `q3c_join`) · 10. Multi-survey SED · 11. DESI bitmask selection ·
12. Density→SIA vetting · 13. LSS wedge · 14. Variable-star (multi-epoch + SIA)
· 15. Open-ended satellite search.

---

## 3. ALMA obscore suite (new — parallel to the 15)

Built only from the 🟢 questions, tiered Tier 1→7, MCP-step separated. **Every
ADQL below is live-validated** (counts as of 2026-07 in parentheses). All rely
on the ALMA `ivoa.obscore` facts now curated in `schema_kb.py`.

Standing rules (mirror the ALMA `usage_notes` + `schema_kb`):
- Resolve names via `vo_target_resolve` — **do not hardcode coordinates**
  (HH 212 sits at Dec −1.048°, an easy place to go wrong).
- Match `band_list` with **exact tokens** (`band_list = '7'`), never
  `LIKE '%1%'` (matches band 10 too).
- Collapse spectral-window rows with `DISTINCT member_ous_uid` (datasets) or
  `DISTINCT proposal_id` (programs).
- `science_keyword` is `;`-delimited → `LIKE`. Cycle is the `proposal_id`
  `YYYY.N` prefix (**no `2020.1`** — COVID gap).

### Tier 1 — Discovery & trivial query

**A1. Schema discovery (no row query).**
"Which ALMA obscore columns tell me the array configuration and the angular
resolution of an observation?"
→ MCP: `vo_schema_describe(archive='alma', table='ivoa.obscore')`; reason over
`antenna_arrays` (pad prefixes DA/DV/CM/PM) + `spatial_resolution`.

**A2. Cone count.**
"How many public ALMA observations point within 1′ of M87?"
→ MCP: `vo_target_resolve('M87')` → obscore `COUNT`.
```sql
SELECT COUNT(*) FROM ivoa.obscore
WHERE data_rights='Public'
  AND s_ra BETWEEN 187.688 AND 187.727 AND s_dec BETWEEN 12.373 AND 12.407
```

### Tier 2 — Single-archive selection / band filter

**A3. Band-filtered target search.** (Adele: "M83 in Band 6")
"Find ALMA Band 6 observations of M83."
→ resolve M83 (204.253, −29.865) → obscore cone + exact band token.
```sql
SELECT DISTINCT member_ous_uid, proposal_id, spatial_resolution, target_name
FROM ivoa.obscore
WHERE band_list = '6'
  AND s_ra BETWEEN 204.0 AND 204.5 AND s_dec BETWEEN -30.1 AND -29.6
  AND science_observation='T'
```

**A4. Public-band inventory.** (Adele: "how many bands have public data")
"How many ALMA receiver bands have any public data?"
→ per-band existence with **exact tokens** (padded to avoid 1-vs-10 collision).
Verified: all of bands 1,3,4,5,6,7,8,9,10 have public data (band 2 never built)
→ **9 bands**.
```sql
-- one probe per band; e.g. band 10:
SELECT COUNT(*) FROM ivoa.obscore
WHERE data_rights='Public'
  AND (band_list = '10' OR band_list LIKE '10 %'
       OR band_list LIKE '% 10' OR band_list LIKE '% 10 %')
```

### Tier 3 — Config / provenance classification

**A5. Cycle + target-class count.** (Adele: "Cycle 10 projects that observed the Sun")
"How many Cycle 10 projects observed the Sun?"  → **1**.
```sql
SELECT COUNT(DISTINCT proposal_id) FROM ivoa.obscore
WHERE proposal_id LIKE '2023.1.%' AND scientific_category='Sun'
```

**A6. Cycle + array-type usage.** (Adele: "Cycle 9 12m/7m/TP")
"How many Cycle 9 programs used the 12-m, 7-m, and Total-Power arrays?"
→ derive array from `antenna_arrays` pad prefixes. Verified Cycle 9 (2022.1):
**12-m 320, 7-m 122, TP 230** distinct programs (they overlap — a program can
use several).
```sql
SELECT COUNT(DISTINCT proposal_id) FROM ivoa.obscore          -- 12-m array
WHERE proposal_id LIKE '2022.1.%'
  AND (antenna_arrays LIKE '%DV%' OR antenna_arrays LIKE '%DA%')
-- 7-m: antenna_arrays LIKE '%CM%'   ·   TP: antenna_arrays LIKE '%PM%'
```

### Tier 4 — Target-centric deep dive

**A7. Deep high-res continuum candidate.** (Adele HH 212, Hard)
"Summarize Band 7 data on HH 212 usable for a deep, better-than-1″ continuum
image." → resolve HH 212 → band 7 + `spatial_resolution < 1` + cone; summarize
the member datasets. Verified: **11 datasets**, best resolution **0.015″**.
```sql
SELECT DISTINCT member_ous_uid, proposal_id, spatial_resolution,
       t_exptime, frequency
FROM ivoa.obscore
WHERE band_list = '7' AND spatial_resolution < 1.0
  AND s_ra BETWEEN 85.9 AND 86.0 AND s_dec BETWEEN -1.1 AND -1.0
  AND science_observation='T'
ORDER BY spatial_resolution
```

### Tier 5 — Line / spectral & bibliographic selection

**A8. Multi-line co-observation.** (Adele: 12CO/13CO/C18O Band 6 same project, Medium)
"List projects where 12CO, 13CO **and** C18O were all observed in Band 6 within
one project." → check the three rest frequencies (230.538 / 220.399 / 219.560
GHz) fall inside `frequency_support` spectral windows, grouped to one
`proposal_id`. Agent-heavy (parse `frequency_support` client-side); the MCP
returns the Band-6 rows per program.

**A9. Recent papers on a topic.** (Adele: recent outflow publications, Easy)
"Give me recent (≥2024) papers that used ALMA data on protostellar outflows."
→ `science_keyword` LIKE + publication columns. Verified: **14** distinct
`bib_reference`.
```sql
SELECT DISTINCT bib_reference, publication_year, first_author, pub_title
FROM ivoa.obscore
WHERE science_keyword LIKE '%Outflows, jets and ionized winds%'
  AND publication_year >= 2024
ORDER BY publication_year DESC
```

### Tier 6 — Cross-archive

**A10. Two-facility overlap.** (Adele: Perseus protostars in ALMA and JWST, Hard)
"Which protostars in Perseus were observed by **both** ALMA and JWST?"
→ ALMA obscore cone/keyword over Perseus ∩ JWST via the registered **CADC**
SIA2 service; match by position. Multi-archive; exercises `vo_archive_list` +
two backends + positional reconciliation.

### Tier 7 — Open-ended

**A11. Agent-designed target selection.**
"Find me a good target for a deep, high-resolution ALMA continuum **mosaic** in
a nearby star-forming region — devise a selection over the archive and rank
candidates." → full agency: `science_keyword` (star formation) + band +
`spatial_resolution` + `is_mosaic='T'` + sensitivity columns, aggregate to
programs, rank, then optionally a datalink/preview per top candidate.

---

## 4. What this branch changes

- `schema_kb.py`: augmented the ALMA `ivoa.obscore` entry with verified facts
  the suite depends on — `proposal_id`→Cycle mapping (incl. the missing
  `2020.1`), `antenna_arrays` pad-prefix→array-type, `spatial_resolution` units,
  `science_keyword` delimiter/vocabulary, and the in-table bibliography columns.
- `docs/mcp-eval-plan.md`: this plan.

Open follow-ups: turn A1–A11 into `tests/workflows/` chains (cassette-backed);
decide whether A4's per-band probe should become a small helper; consider a
`schema_kb` entry documenting `frequency_support` parsing for A8.
