A production OpenSearch cluster manages three index patterns (`applogs-*`, `security-*`, `metrics-*`) under separate ISM lifecycle policies. Over 15 days of operation, operators have observed indices stalling in intermediate lifecycle states, shard allocation anomalies, and inconsistent rollover behavior. A comprehensive forensic analysis is needed to identify every operational issue, determine root causes, and produce actionable fixes.

Cluster state snapshots (native OpenSearch REST API JSON format) are at `/app/cluster/`. Current ISM policy definitions are at `/app/policies/`. An ISM semantics reference is at `/app/reference/ism_spec.md`. The required output specification is at `/app/output_spec.json`.

Produce `/app/run_forensics.sh` that, when executed, investigates the cluster state data, identifies every ISM operational issue across all managed indices, and generates all outputs conforming to `/app/output_spec.json`.

Run: `bash /app/run_forensics.sh`