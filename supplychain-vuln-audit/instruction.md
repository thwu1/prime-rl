A Node.js application at `/app/` relies on five custom internal libraries under `/app/lib/`: `config-flatten`, `cmd-builder`, `input-validator`, `archive-utils`, and `telemetry-helper`. A security incident response requires a comprehensive audit. Multiple vulnerability classes are suspected across the codebase, and threat intelligence suggests one module may harbor an intentional supply chain backdoor performing covert data exfiltration.

Unmodified copies of all modules are preserved at `/app/.originals/` for reference and exploit testing.

## Required Deliverables

All output under `/app/`:

**`sarif_report.json`** -- Valid SARIF v2.1.0 static analysis report covering every discovered vulnerability. Must include `$schema`, `version` `"2.1.0"`, a tool driver with named rules (one per vulnerability class), and result entries with rule IDs, severity levels (`level`), descriptive messages, and physical source locations referencing files under `lib/`.

**`exploits/*.js`** -- Proof-of-concept Node.js scripts (one per non-backdoor vulnerability). Each must exploit the original vulnerable code at `/app/.originals/` and exit 0 on success.

**`audit_report.json`** -- JSON array of findings. Each entry must contain at minimum: `module_name`, `cwe_id` (e.g. `"CWE-1321"`), `vulnerability_type`, `severity`, and `description`.

**`dns_exfil_log.json`** -- Captured DNS exfiltration traffic from the backdoor module. Instrument the module's DNS resolution (e.g. monkey-patch `dns.resolve`) to intercept outbound queries while `SECRET_CANARY=TB_AUDIT_2024_f7e3a` is set in the environment. Must be a JSON object with an `intercepted_queries` array where each entry has at least a `hostname` field showing the queried domain. The captured queries must contain hex-encoded exfiltrated data and reference the decoded C2 domain.

**`backdoor_analysis.json`** -- Supply chain compromise details: `technique`, `target` (decoded endpoint/domain), `data_stolen`, and `obfuscation_method`.

**Fixed source code** -- All vulnerabilities patched in-place under `/app/lib/`. Module APIs and legitimate functionality must remain intact.