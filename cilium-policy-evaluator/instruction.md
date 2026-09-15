A Cilium-managed Kubernetes cluster's runtime state has been captured in `/app/`. Your task is to determine the correct traffic flow verdict for each query.

## Deployment State

- `/app/cilium-state.db` — SQLite database containing the cluster's endpoint registry, security identity mappings, and per-endpoint label assignments (as populated by the Cilium agent)
- `/app/policies/` — Namespace-scoped `CiliumNetworkPolicy` resources currently applied
- `/app/clusterwide-policies/` — `CiliumClusterwideNetworkPolicy` resources applied cluster-wide
- `/app/cilium-source/` — Excerpts from the Cilium policy engine source code (Go), for reference on how the agent evaluates policies
- `/app/semantics.md` — Reference document describing the exact evaluation semantics
- `/app/flows.json` — Traffic flow queries to evaluate

## Required Output

Produce `/app/results.json` — a JSON array where each element has the fields:
- `id` (string) — the query identifier
- `from` (string) — source endpoint name
- `to` (string) — destination endpoint name
- `port` (int) — destination port
- `protocol` (string) — transport protocol
- `verdict` (string) — either `"ALLOWED"` or `"DENIED"`

The verdicts must match what Cilium's policy enforcement engine would produce given the deployed policies and endpoint state.