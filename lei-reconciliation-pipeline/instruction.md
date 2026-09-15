A compliance team suspects data integrity issues in their entity tracking system and requires a forensic regulatory assessment against the GLEIF (Global Legal Entity Identifier Foundation) LEI registry — the authoritative source for Legal Entity Identifier data maintained under ISO 17442.

The portfolio at `/app/data/portfolio.json` contains records with `lei`, `local_name`, `local_country`, `local_jurisdiction`, and `local_reg_status` fields. The assessment must evaluate structural validity, registration health (including conformity and corroboration status), corporate ownership topology with reporting exception analysis, cross-border regulatory exposure, metadata integrity, and composite risk classification.

Produce `/app/output/report.json` with these sections:

**`checksum_validation`** — Classify each LEI by structural validity per ISO 17442. Contains `valid_leis` (array of valid LEI strings) and `invalid_leis` (array of objects with `lei` and `reason`).

**`registry_assessment`** — For each valid LEI, retrieve authoritative data from the GLEIF API. `entities` dict keyed by LEI, each containing: `legal_name`, `country`, `jurisdiction`, `registration_status`, `conformity_flag`, `corroboration_level`, `managing_lou` (LEI of the managing Local Operating Unit), `bic` (list of BIC codes or empty list), and `relationship_registration_status` (the registration status of the parent-child relationship record for subsidiaries, or null for top-level entities).

**`ownership_topology`** — Map corporate ownership structure:
- `conglomerates`: array, each with `ultimate_parent_lei`, `ultimate_parent_name`, `subsidiaries` (LEI list), `subsidiary_count`, `jurisdictions_spanned` (unique jurisdiction codes across the group), `cross_border_links` (count of parent-child pairs in different countries)
- `standalone_entities`: array of LEIs with no ownership links
- `reporting_exceptions`: dict keyed by LEI for top-level entities that file GLEIF parent reporting exceptions instead of declaring a parent relationship, each with `exception_category` and `exception_reason` as retrieved from the registry
- `max_depth`: deepest ownership chain depth

**`metadata_discrepancies`** — Compare each valid entity's local fields against registry. `discrepancies` array, each with `lei`, `field`, `local_value`, `registry_value`. Compare name (case-insensitive), country, and jurisdiction.

**`risk_classification`** — Classify each valid entity by cumulative risk. Risk factors: (1) registration status not ISSUED, (2) conformity flag not CONFORMING, (3) corroboration level not FULLY_CORROBORATED, (4) relationship registration LAPSED for subsidiaries, (5) metadata discrepancies present for this entity. `classifications` dict keyed by LEI with `risk_tier` (HIGH: ≥3 factors, MEDIUM: 1–2, LOW: 0) and `risk_factors` (list of applicable factor descriptions).

**`summary`** — `total_entities`, `valid_checksums`, `invalid_checksums`, `conglomerate_count`, `discrepancy_count`, `high_risk_count`, `medium_risk_count`, `low_risk_count`.

The GLEIF API base URL is `https://api.gleif.org/api/v1`. Responses follow JSON:API format.