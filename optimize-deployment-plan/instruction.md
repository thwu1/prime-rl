`/app/architecture.json` describes a 28-component distributed expense management platform, 8 heterogeneous deployment nodes, 30 inter-component dependencies, and quality attribute requirements.

Produce `/app/deployment_plan.json` that assigns every component to exactly one deployment node, satisfies all constraints, and minimizes total hourly infrastructure cost.

## Constraints

1. **Capacity**: Aggregate CPU and memory of components on a node must not exceed its capacity.
2. **Security zones**: Component `security_classification` must be ≤ the node's `security_zone` per the hierarchy `public < internal < restricted`. A "restricted" component requires a "restricted" node; "internal" requires "internal" or higher.
3. **Affinity**: Component pairs with `same_node` rules must share a node.
4. **Anti-affinity**: Component pairs with `different_node` rules must be on distinct nodes.
5. **Latency**: Each latency scenario specifies an ordered component path and a budget. End-to-end latency = Σ `processing_time_ms` for each component in the path + Σ network hop latencies between consecutive components. Hop latency: same node = 0.5 ms, same AZ different node = 2.0 ms, cross-AZ = 8.0 ms. Total must be ≤ the scenario's `max_end_to_end_ms`.
6. **AZ distribution**: Specified component groups must span at least `min_zones` distinct availability zones.
7. **Cost**: Total hourly cost (sum of `cost_per_hour` for each node with ≥1 assigned component) must be ≤ $21.00.

## Output

```json
{
  "assignments": {"<component-id>": "<node-id>", ...},
  "total_cost_per_hour": <float>,
  "nodes_used": ["<node-id>", ...]
}
```

`total_cost_per_hour` and `nodes_used` must be consistent with `assignments`.