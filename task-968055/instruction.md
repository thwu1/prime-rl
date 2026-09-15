A Kubernetes cluster running a microservices application (frontend, backend-api, database, redis) in the `production` namespace has been compromised. Security teams have captured API server audit logs and Falco runtime alerts from the incident window.

Analyze the audit logs at `/app/audit-logs/kube-apiserver-audit.json`, Falco alerts at `/app/falco-events/alerts.jsonl`, and current deployment manifests at `/app/manifests/` to identify the compromised identity, reconstruct the full attack chain, and generate defensive security policies. Reference `/app/cluster-info.md` for cluster architecture context.

Produce the following files under `/app/output/`:

**`forensic-report.json`** -- JSON object with keys: `compromised_identity` (object with `username`, `namespace`, `service_account_name`), `attack_source_ip` (string), and `attack_events` (chronologically-ordered array where each element has `timestamp`, `audit_id`, `verb`, `resource`, `namespace`, `name`, `mitre_technique`, `description`). Map each attack event to a MITRE ATT&CK technique ID.

**`audit-policy.yaml`** -- A Kubernetes `audit.k8s.io/v1` `Policy` resource with rules that would detect similar attacks. Sensitive resources must be logged at `RequestResponse` or `Request` level. Include rules covering secrets, RBAC resources, pod mutations in system namespaces, and workload controller modifications.

**`network-policies/`** -- Directory of Kubernetes `NetworkPolicy` YAML files (`networking.k8s.io/v1`) implementing least-privilege network segmentation for each production workload based on the application architecture. Database and cache tiers must only accept ingress from the API tier.

**`falco-rules.yaml`** -- At least 3 custom Falco rules (valid Falco YAML list format with `rule`, `condition`, `output`, `priority` fields) targeting the specific attack patterns observed in this incident.