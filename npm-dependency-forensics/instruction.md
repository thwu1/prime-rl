A Node.js data processing application at `/app/` uses four direct npm dependencies (pinned in `package.json`) for YAML parsing, JSON flattening, tar extraction, and CSS selector filtering. All four installed versions contain known security vulnerabilities. Do NOT use `npm audit`.

Produce a complete security audit consisting of:

- **`/app/vulnerability_report.json`** — A JSON array where each element represents one vulnerable dependency and contains: `package`, `installed_version`, `cve` (CVE ID string or `null`), `ghsa` (GHSA ID string), `cwe` (CWE ID string), `cvss_v3_score` (float), `severity` (critical/high/medium/low), `patched_version`, and `description` (one-line summary). All four packages must be covered with accurate advisory metadata sourced from public databases (GitHub Advisory Database, NVD, etc.).

- **`/app/exploits/`** — A working exploit script for each vulnerability, named after its CWE class in snake_case (e.g. `prototype_pollution.js`, `code_injection.js`, `path_traversal.js`, `redos.js`). Each script must use the installed vulnerable package to trigger the flaw, print `VULN_CONFIRMED: <description>` to stdout on success, and exit 0 (exit 1 on failure).

- **`/app/mitigations/`** — A corresponding mitigation script for each exploit, with suffix `_safe.js` (e.g. `prototype_pollution_safe.js`). Each must apply a code-level defense that neutralizes the vulnerability WITHOUT upgrading the package, re-run the attack to prove it no longer succeeds, print `MITIGATED: <description>` to stdout, and exit 0.