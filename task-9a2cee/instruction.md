Six npm package tarballs are at `/app/tarballs/`. Registry metadata with expected SHA-512 SRI integrity hashes is at `/app/registry/` (one JSON file per package). An advisory intelligence feed is at `/app/advisories/advisories.ndjson`. Baseline static analysis rules in semgrep YAML format are at `/app/semgrep-rules/npm-malware.yaml`.

Conduct a forensic supply chain audit covering three attack surfaces:

**Integrity verification** — Compute each tarball's SHA-512 hash in SRI format (`sha512-<base64>`) and compare against the `integrity` value in its corresponding registry metadata file. Report matches and mismatches.

**Static code analysis** — The provided semgrep rules detect only a subset of threats. Write additional custom semgrep rules to detect DNS-based data exfiltration, destructive file operations, and outbound HTTP data callbacks. Scan all extracted package source code with both the provided and your custom rules. Each compromised package's `evidence` array must include at least one entry prefixed with `semgrep:` naming the matched rule.

**Advisory cross-reference** — The NDJSON feed contains advisories with `package_pattern` (glob) and `indicators` (string array) fields. For each package, identify advisories whose pattern matches the package name AND whose indicators are substantiated by strings actually present in the package source code. Advisories that match only by name pattern but whose indicators are absent from the code are false positives and must be excluded.

Write your complete findings to `/app/audit_report.json` conforming to the schema at `/app/schema.json`. All 6 packages must appear in the `audit` array.

Packages: `config-utils-1.2.0.tgz`, `log-helper-2.1.0.tgz`, `string-tools-0.9.1.tgz`, `data-store-3.0.0.tgz`, `path-resolver-1.0.3.tgz`, `build-runner-2.0.1.tgz`.