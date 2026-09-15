A production Kubernetes cluster experienced a security incident on 2024-11-15. You have been engaged as an incident responder. All evidence is staged under `/app/`.

## Evidence

- `/app/audit-logs/kube-apiserver-audit.jsonl` — API server audit log (JSONL) covering the incident window. **Warning**: the log was collected under duress and may contain integrity issues (malformed entries, truncated writes, concatenated lines). Robust parsing is required.
- `/app/falco-events/events.log` — Runtime security alerts from Falco. Note that alerts from multiple containers within the same pod will be interleaved — distinguish attack activity from legitimate sidecar operations.
- `/app/falco-rules/falco_rules_reference.yaml` — Reference Falco macros, lists, and example rules
- `/app/context/authorized-operations.txt` — Pre-approved maintenance operations during the window (multiple service accounts were active)
- `/app/context/cluster-info.txt` — Cluster topology and RBAC documentation

## Deliverables

Analyze all evidence, correlate across data sources, distinguish authorized from malicious activity, identify evidence anomalies, and produce three artifacts in `/app/output/`:

**`/app/output/incident-report.json`** — Valid JSON. Reconstruct the full attack chain: identify the compromised identity, document the root cause RBAC vulnerability that enabled the breach, catalog all exfiltrated secrets, detail lateral movement and persistence mechanisms, map behaviors to MITRE ATT&CK technique IDs (minimum 3), and provide remediation recommendations. Must cross-correlate API audit logs with Falco runtime evidence. Investigate and document any network-layer anomalies (e.g., source IP inconsistencies across the attacker's session). Verify whether persistence mechanisms were activated post-creation.

**`/app/output/hardened-audit-policy.yaml`** — Valid Kubernetes `audit.k8s.io/v1` Policy. Must include rules covering secrets access, RBAC mutations, pod exec/attach, and serviceaccount lifecycle at appropriate audit levels. Include noise reduction rules (level: None) and a catch-all. Must be production-viable.

**`/app/output/custom-falco-rules.yaml`** — Valid YAML list of custom Falco rules targeting the runtime attack behaviors observed in the evidence. Each rule requires: rule, desc, condition, output, priority, tags. Use valid syntax compatible with the reference macros and lists. Minimum 3 rules covering shell spawning, sensitive file access, and binary/network/package activity in containers.