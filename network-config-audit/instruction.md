Router configurations for a 6-router enterprise network are at `/app/configs/` (R1.cfg through R6.cfg). The network design specification is at `/app/design_spec.json`. Operational state snapshots captured from the live network are at `/app/operational_data/`.

The deployed network does not fully conform to the design specification. Configuration deviations exist across multiple protocol domains and affect routing behavior, security posture, and operational resilience. The specific issues are not catalogued — discovering them through systematic comparison of each router's running configuration against the design intent is part of the task. The operational state data contains observable symptoms that should be cross-referenced to corroborate and prioritize findings.

Produce the following deliverables:

1. **`/app/audit_report.json`** — JSON object with a top-level `defects` array. Each element must have:
   - `router`: hostname (R1–R6)
   - `category`: `"security"`, `"routing"`, or `"operational"`
   - `severity`: `"critical"`, `"high"`, or `"medium"`
   - `risk_score`: integer 1–10 quantifying blast radius and operational impact
   - `description`: the deviation, its operational consequences, and corroborating evidence from operational data where available
   - `affected_config`: the specific problematic configuration line(s)
   - `remediation`: corrected IOS-XE configuration commands
   - `migration_phase`: integer (lower = earlier) reflecting safe change ordering that avoids adjacency disruptions during remediation

2. **`/app/remediation_patches/`** — For each router with defects, a unified diff patch file (e.g., `R1.patch`) generated with `diff -u` between the original configuration and the corrected version.

3. **`/app/migration_plan.json`** — JSON array of phase objects, each with:
   - `phase`: integer
   - `routers`: list of routers changed in this phase
   - `changes_summary`: what changes are applied
   - `dependency_reason`: why this phase ordering is necessary
   - `rollback_risk`: `"low"`, `"medium"`, or `"high"`

4. **`/app/topology.svg`** — Network topology diagram rendered from a Graphviz DOT source file (`/app/topology.dot`) using `dot -Tsvg`. Nodes represent routers, edges represent links, and discovered defects are annotated on the affected elements.