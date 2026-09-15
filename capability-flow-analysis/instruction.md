A satellite flight-control system built on the seL4 microkernel uses capability-based access control governed by a compartmented security lattice. The full system specification is at `/app/system_spec.json`, including the security model with its dominance rule, protection domains with security labels, typed resources, and capabilities with delegation chains.

Analyze the system for information-flow security violations and produce a minimum-cost remediation plan. Write results to `/app/results.json` conforming to the schema below.

## Output Schema (`/app/results.json`)

The output must be a JSON object with exactly these fields:

| Field | Type | Description |
|---|---|---|
| `inert_capability_ids` | `string[]` | Sorted list of capability IDs that grant no effective access. Derived capabilities cannot exercise rights unavailable through their delegation ancestry. |
| `flow_edges` | `[string, string, string][]` | All directed information-flow triples `[source_pd, dest_pd, resource]` implied by non-inert capabilities. Exclude self-loops. Flow direction depends on the resource type and the nature of the rights held by each PD. |
| `violations` | `[string, string, string][]` | Subset of `flow_edges` where the destination's security label does not dominate the source's per the security model's dominance rule. |
| `tcb` | `{string: string[]}` | For each PD, the sorted list of all other PDs that can transitively send information to it via the flow graph. |
| `impact_boundary` | `{string: string[]}` | For each PD, the sorted list of all other PDs it can transitively reach via the flow graph. |
| `min_revocations` | `object[]` | Minimum-cost set of capabilities to directly revoke to eliminate all violations. Each entry: `{"id": string, "pd": string, "resource": string, "cost": int}`. Revoking a capability also revokes all its descendants in the delegation hierarchy at no extra cost. |
| `total_revocation_cost` | `int` | Sum of `cost` values in `min_revocations`. |
| `cascaded_revocation_ids` | `string[]` | Sorted list of capability IDs revoked indirectly as descendants of directly-revoked capabilities (must not appear in `min_revocations`). |