You are auditing the network security posture of a multi-tier Kubernetes application protected by CiliumNetworkPolicies. Determine whether each of 30 network connections would be allowed or denied by the deployed policy configuration.

## Environment

The cluster's policy configuration is split across multiple sources that must be consolidated:

- `/app/policies/` — Four CiliumNetworkPolicy YAML files applied directly to the cluster.
- `/app/policies-chart/` — A Helm chart containing additional CiliumNetworkPolicy templates with parameterized values. These policies are not yet rendered.
- `/app/endpoint-state.json` — Endpoint state dump from `cilium-dbg endpoint list -o json`. Contains managed endpoint identities, networking addresses, and security labels in Cilium's internal format.
- `/app/entities.json` — Cluster entity-to-CIDR mappings for identity resolution.
- `/app/connections.json` — 30 network connections to audit (source IP, destination IP, destination port, protocol).
- `/app/reference/` — Cilium policy API type definitions and enforcement documentation.

## Task

Produce a verdict for each connection by evaluating it against the full set of deployed CiliumNetworkPolicies, following Cilium's actual enforcement semantics. Each connection should be classified as either `"ALLOW"` or `"DENY"`.

## Output

Write `/app/verdicts.json` — a JSON array of 30 objects, each with `id` (int) and `verdict` (`"ALLOW"` or `"DENY"`), ordered by id.