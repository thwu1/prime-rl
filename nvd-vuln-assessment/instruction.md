Build a vulnerability assessment engine that evaluates a software inventory against NVD CVE data.

**Inputs** at `/app/`:
- `nvd_dataset.json` — 10 CVE records in NVD API 2.0 format. Each has a CVSS v3.1 vector string (no precomputed base scores), CWE weakness classifications, and CPE configurations with version-range matching criteria.
- `inventory.json` — 12 software items, each with `vendor`, `product`, and `version`.

**Required outputs** at `/app/`:

1. `assessment.json` — JSON vulnerability assessment:
   - `assessed_items`: array of all 12 inventory items, each with `vendor`, `product`, `version`, `cves` (array of matched CVEs, each with `id`, `cvss_v3_1_score`, `severity`, `cwes`), and `risk_score` (highest CVSS among matched CVEs, or `0.0`).
   - `statistics`: object with `total_items`, `affected_items`, `unaffected_items`, `total_cve_matches`, and `by_severity` (object with `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` integer counts).

2. `cvss_calc.py` — Standalone CVSS v3.1 base score calculator. Usage: `python3 /app/cvss_calc.py "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"` outputs `9.8` to stdout.

**Technical requirements:**
- Compute CVSS v3.1 base scores from vector strings using the specification's formulas, metric value lookup tables, and Roundup function. Note: Privileges Required (PR) metric values depend on Scope.
- Match inventory items against CPE configurations using `versionStartIncluding`, `versionStartExcluding`, `versionEndIncluding`, `versionEndExcluding`. Version comparison must correctly handle multi-component versions (e.g., `2.4.49` vs `2.4.50`) and versions with alphabetic suffixes (e.g., `1.0.1c` < `1.0.1g`).
- Severity thresholds: CRITICAL >= 9.0, HIGH >= 7.0, MEDIUM >= 4.0, LOW >= 0.1, NONE = 0.0.