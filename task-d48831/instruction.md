A production Kubernetes cluster running a microservices e-commerce application has been breached. The security team collected kube-apiserver audit logs and Falco runtime alerts spanning the incident window. Perform forensic analysis and produce hardening artifacts that would prevent recurrence.

Evidence at `/app/`:
- `/app/audit-logs/kube-apiserver-audit.jsonl` — API server audit events
- `/app/audit-logs/falco-alerts.jsonl` — Falco runtime alerts
- `/app/manifests/workloads.yaml` — pre-incident workload definitions
- `/app/cluster-info.md` — cluster topology and configuration
- OPA binary at `/usr/local/bin/opa`

Produce four artifacts:

**Incident report** (`/app/analysis/incident-report.json`): JSON with `compromised_identity` (object: `type`, `name`, `namespace`), `attack_chain` (array of objects: `step`, `timestamp`, `tactic`, `description` — use MITRE-style tactic labels like Discovery, Privilege Escalation, Persistence, Execution, Impact, Collection), `affected_namespaces` (array), `indicators_of_compromise` (array), and `severity` (string).

**OPA admission policy** (`/app/policies/admission.rego`): Rego policy under `package kubernetes.admission` with `deny[msg]` rules blocking the attack vectors found in the logs. Must handle both direct Pod specs and embedded pod template specs in controllers (Deployments, DaemonSets, etc.). Pods in namespace `kube-system` with label `system-component: "true"` must be exempt. Policy input follows the standard admission review structure (`input.review.object`).

**Falco rules** (`/app/policies/falco_rules.yaml`): YAML list of custom Falco rules detecting the runtime attack patterns from the alerts. Each entry needs `rule`, `desc`, `condition`, `output`, and `priority` fields.

**Audit policy** (`/app/policies/audit-policy.yaml`): Kubernetes audit policy (`apiVersion: audit.k8s.io/v1`, `kind: Policy`) with rules logging sensitive resource operations at levels sufficient to capture evidence of similar attacks.