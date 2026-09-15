`/app/system.json` describes a safety-critical microkernel system (inspired by the OSmosis isolation model and seL4 Microkit architecture) with protection domains, shared-memory resources, access rights, and isolation constraints. The system configuration is unique to this instance — read it to determine the exact topology.

Implement a program that reads `/app/system.json` and writes a complete isolation analysis to `/app/results/`.

## Information Flow Semantics

Information flows from PD **a** to PD **b** through resource **r** when **a** has `write` or `readwrite` permission on **r** AND **b** has `read` or `readwrite` permission on **r**, with a != b. Transitive information flow is the transitive closure of these direct flows.

- **TCB(pd)**: all PDs (including itself) that can transitively reach `pd` via directed information flow.
- **Impact(pd)**: all PDs (including itself) that `pd` can transitively reach.
- **Violation**: constraint `(a, b)` is violated if `a` can reach `b` **or** `b` can reach `a` in the transitive flow graph.
- **Min Resource Cut** from `a` to `b`: minimum-cardinality set of resources whose removal (revoking all access) eliminates every directed information flow path from `a` to `b`. Formulated as max-flow on the bipartite PD-Resource network: each resource node splits into `R_in -> R_out` (capacity 1); edges `PD -> R_in` (capacity infinity) for write/readwrite access; edges `R_out -> PD` (capacity infinity) for read/readwrite access.

## Instance Token

`/app/system.json` contains a unique `dna_token` field. Every output file must include this token under the key `_instance_token` at the top level. This binds your analysis to this specific system instance.

## Required Outputs (`/app/results/`)

**`info_flow.json`** -- direct information flow edges. Format: `{"_instance_token": "...", "data": {src_pd: {dst_pd: [sorted enabling resource IDs], ...}, ...}}`. Only PDs with outgoing flows appear as keys in `data`.

**`tcb.json`** -- `{"_instance_token": "...", "data": {pd_id: [sorted list of PD IDs in its TCB], ...}}` for all PDs.

**`impact.json`** -- `{"_instance_token": "...", "data": {pd_id: [sorted list of PD IDs in its impact boundary], ...}}` for all PDs.

**`violations.json`** -- `{"_instance_token": "...", "data": [...]}` where `data` is a JSON array matching the constraint order in `system.json`:
```
[{"pd_a": "...", "pd_b": "...", "violated": true/false,
  "forward_path": [pd_ids...] or null, "forward_length": int or null,
  "reverse_path": [pd_ids...] or null, "reverse_length": int or null}]
```
`forward` = `pd_a -> pd_b`, `reverse` = `pd_b -> pd_a`. Report shortest paths (BFS). `null` if no path exists in that direction.

**`min_cuts.json`** -- `{"_instance_token": "...", "data": [...]}` where `data` is a JSON array for **violated** constraints only:
```
[{"pd_a": "...", "pd_b": "...",
  "forward_cut_size": int, "forward_cut_resources": [sorted resource IDs],
  "reverse_cut_size": int, "reverse_cut_resources": [sorted resource IDs]}]
```
If no path exists in a direction, cut size is 0 and resources is `[]`. The reported resources must form a valid cut (removing them eliminates all paths in that direction).