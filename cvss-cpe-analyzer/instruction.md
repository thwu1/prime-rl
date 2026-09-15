A security team's NVD mirror database at `/app/data/nvd_mirror.db` has been compromised — records may have been altered after initial ingestion. The database uses a single `cve_records` table with columns: `cve_id`, `description`, `published`, `last_modified`, `vuln_status`, `cvss_vector`, `cvss_base_score`, `cvss_severity`, `cwe_id`, `cpe_config` (JSON blob queryable via SQLite JSON1), `hmac_sha256`.

Available data sources:
- Integrity signing protocol documentation: `/app/data/signing_protocol.txt`
- Signing key: `/app/data/.hmac_key`
- Canonical NVD API 2.0 snapshot (ground truth): `/app/data/canonical/nvd_snapshot.json`
- EPSS probability scores (CSV with comment header): `/app/data/feeds/epss_scores.csv`
- CISA KEV catalog: `/app/data/feeds/kev_catalog.json`
- Software asset inventory: `/app/data/inventory.json`
- Threat scoring policy: `/app/data/scoring_policy.json`

Perform a forensic audit and produce two output files:

**`/app/output/audit_report.json`** containing:
- `tampered_records`: records that fail integrity verification per the signing protocol (`cve_id`, `hmac_stored`, `hmac_computed`)
- `score_anomalies`: CVEs where the stored CVSS base score does not match the score derivable from the CVSS vector string (`cve_id`, `stored_score`, `computed_score`, `vector_string`)
- `cpe_discrepancies`: CVEs whose CPE configurations in the DB differ from the canonical snapshot (`cve_id`)
- `cwe_errors`: CVEs whose CWE mappings in the DB differ from the canonical snapshot (`cve_id`, `stored_cwe`, `correct_cwe`)
- `threat_priority`: vulnerable inventory items scored per `/app/data/scoring_policy.json`, with fields `vendor`, `product`, `version`, `matched_cves`, `cvss_score`, `epss_score`, `in_kev`, `priority_score` — sorted descending by `priority_score`
- `summary`: `total_cves_audited`, `tampered_count`, `score_anomalies_found`, `cpe_discrepancies_found`, `cwe_errors_found`, `inventory_items_total`, `inventory_items_vulnerable`, `risk_score` (computed per scoring policy)

**`/app/output/cpe_dictionary.xml`**: CPE Dictionary 2.3 XML listing affected inventory products. Each `cpe-item` must have a CPE 2.2 URI `name` attribute, a `title` element, and a `cpe-23:cpe23-item` child with the CPE 2.3 formatted string. Derive the correct CPE part type (`a`/`o`/`h`) from the matching vulnerability's CPE criteria. Namespaces: `http://cpe.mitre.org/dictionary/2.0` (default) and `http://scap.nist.gov/schema/cpe-extension/2.3` (cpe-23).

The canonical NVD snapshot is the authoritative source for CPE configurations and CWE classifications. The database should not be trusted for these fields.