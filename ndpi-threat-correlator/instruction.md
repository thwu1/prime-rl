Workstation `10.0.1.50` has been flagged for suspected compromise. Two data sources from the investigation are staged in `/app/data/`:

- `ndpi_flows.txt` — nDPI `ndpiReader` flow-level traffic analysis (epoch timestamps via `-T 1`)
- `threat_intel.json` — Threat intelligence feed with known-bad indicators (IPs, domains, JA4 fingerprints, certificate SHA-1 hashes)

A JSON Schema defining the required report structure is at `/app/schema.json`. Read the schema carefully — it specifies every required section, field name, data type, and nesting. Indicators from the threat intel feed that were not observed in any traffic flow must be omitted from the matches.

Produce two deliverables:

1. **`/app/report.json`** — Incident response report conforming exactly to `/app/schema.json`. All data sources must be cross-correlated.

2. **`/app/rules.rules`** — Suricata IDS rules (standard Suricata rule syntax, one rule per line) to detect the identified threats in future traffic. Each rule must include `msg`, `sid`, and `rev` keywords.