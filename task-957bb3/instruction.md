A production Kubernetes cluster running an e-commerce platform (namespaces: `ecommerce`, `monitoring`, `kube-system`) has been flagged for suspicious API server activity. The security team needs a complete incident analysis and hardened security configurations.

## Available Artifacts

- `/app/audit-logs/kube-apiserver-audit.json` — API server audit log (mix of legitimate and potentially malicious events)
- `/app/cluster-state/current-rbac.yaml` — Current RBAC resources
- `/app/cluster-state/current-workloads.yaml` — Current workloads snapshot

## Required Output

Produce all deliverables under `/app/results/`:

| Path | Content |
|---|---|
| `attack_summary.json` | JSON forensic report: `attack_timeline` (chronological array of attacker-only events, each with `timestamp`, `action`, `resource_type`, `resource_name`, `namespace`, `description`), `compromised_service_account` (full username), `compromised_secrets` (`namespace/name` array), `attacker_created_resources` (`Kind/namespace/name` or `Kind/name` array), `attacker_source_ip`, `initial_vulnerability` (one-line) |
| `remediation/webapp-rbac.yaml` | Hardened RBAC for the webapp service account — its legitimate needs are reading services and configmaps in `ecommerce` only |
| `remediation/audit-policy.yaml` | `audit.k8s.io/v1` Policy that would have detected the attack patterns you identified |
| `remediation/network-policy.yaml` | NetworkPolicy for `ecommerce` — webapp ingress on port 8080, egress to database on port 5432, deny all other traffic |
| `remediation/falco-rules.yaml` | Falco runtime detection rules targeting the attack patterns you identified |
| `trivy-scan/current-state.json` | JSON misconfiguration scan results for `/app/cluster-state/` |
| `policies/*.rego` | Rego validation policies that enforce security best practices on your remediation configs |
| `conftest-results.json` | JSON validation output confirming all remediation YAML files pass your Rego policies |