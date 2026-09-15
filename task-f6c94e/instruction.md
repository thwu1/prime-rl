The security operations team has flagged the vulnerability assessment pipeline at `/app/` for producing incorrect triage results. An incident report at `/app/incident_report.txt` documents the discrepancies discovered during audit.

The pipeline consists of two stages:

1. A traffic analysis module (`/app/traffic_analyzer.sh`) that uses `tshark` to analyze network capture data (`/app/traffic.pcap`) for active exploit signatures, producing `/app/active_threats.json`.

2. A vulnerability assessment script (`/app/vuln_assess.py`) that reads CVE data from a SQLite database (`/app/vulndb.sqlite`), matches against a software inventory (`/app/inventory.json`), applies CVSS v3.1 environmental modifiers from `/app/env_config.json`, incorporates active threat intelligence from `/app/active_threats.json`, and generates prioritized remediation reports.

Investigate all pipeline components — database contents, configuration, network analysis scripts, and assessment code — to identify and fix all root causes of incorrect output. After all fixes, running `bash /app/traffic_analyzer.sh` followed by `python3 /app/vuln_assess.py` must produce correct:

- `/app/active_threats.json` — 3 CVEs with observed exploit traffic
- `/app/score_validation.json` — CVSS v3.1 base scores for all 10 CVEs
- `/app/affected_inventory.json` — CVE-to-inventory-item mapping (8 CVEs should match)
- `/app/remediation_report.json` — Prioritized report with environmental scores and active exploitation flags, sorted by active exploitation status descending, environmental score descending, base score descending, CVE ID ascending

Beyond fixing the pipeline, the organization is adopting SSVC (Stakeholder-Specific Vulnerability Categorization) for triage decisions. The SSVC decision policy is defined in `/app/ssvc_policy.json` and asset mission criticality data is in `/app/mission_impact.json`. Using the corrected pipeline output, evaluate each vulnerability that affects inventory items against the SSVC framework and produce `/app/ssvc_decisions.json` — a JSON array where each entry contains the CVE ID, the determined value for each SSVC decision point (exploitation, automatable, technical_impact, mission_prevalence), and the final triage decision (Act, Attend, Track*, or Track). Entries must be ordered by decision priority (Act first, then Attend, Track*, Track), with CVE IDs sorted ascending within each tier.