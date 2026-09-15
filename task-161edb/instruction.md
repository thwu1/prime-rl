A developer reported unexpected outbound connections after upgrading the `quickcalc` Python library. The security team has staged all evidence at `/app/`:

- `/app/packages/` — Six package versions (v1.0.0 through v1.2.2)
- `/app/logs/` — Build server logs, network traffic, PyPI records, WHOIS data
- `/app/artifacts/` — File recovered from a compromised build server's Python site-packages
- `/app/report/schema.json` — Required output schema

Produce two deliverables:

**Forensic report** at `/app/report/analysis.json` conforming to `/app/report/schema.json`. The schema defines all required fields including version classifications, IOCs, attack chain reconstruction with timeline, MITRE ATT&CK technique mappings, and per-version severity assessments with justification.

**Semgrep detection rule** at `/app/report/detect_malware.yaml` that flags all malicious Python source files across the package versions with zero false positives on clean code. `semgrep` is pre-installed.