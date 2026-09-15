A production TiDB v7.5 cluster serving an e-commerce platform has accumulated four open incidents. The departing on-call DBA left a diagnostic workspace at `/app/` containing captured artifacts but no analysis.

Your task is twofold:

1. **Incident diagnosis**: Investigate the workspace, determine what data sources and tools are available, and produce a diagnostic report for each incident as `/app/reports/case1.json` through `/app/reports/case4.json`. Each report must conform to the field specifications defined in `/app/output_spec.json` and `/app/schema.json`.

2. **Cluster-wide risk evaluation**: Cross-reference your incident findings with the cluster's operational state to produce `/app/reports/triage_summary.json` — a synthesized assessment that classifies incidents by root cause category, ranks them by production impact, and evaluates cluster-level risk indicators. The specification for this report is also in `/app/output_spec.json`.

Floating-point values must be accurate within 5% relative tolerance.