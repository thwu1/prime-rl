Implement an optimal evaluation planner for matrix chain products with structural properties and transposed operands.

A SQLite database at `/app/input/benchmarks.db` contains three tables:

- `cost_measurements` — empirical FLOP measurements for matrix multiplications across different structural-property combinations. The agent must reverse-engineer the underlying BLAS kernel cost model (the formulas are NOT documented anywhere in the database) by analyzing the relationship between `(left_prop, right_prop, m, k, n)` and `measured_cost`.
- `propagation_rules` — how structural properties (general, symmetric, upper_triangular, lower_triangular, diagonal) propagate through multiplication: given `left_prop` and `right_prop`, what is `result_prop`?
- `transpose_properties` — how transposing a matrix transforms its structural property.

The file `/app/input/chains.json` defines six matrix chain problems. Each chain has named matrices with dimensions and structural properties, and an operand list that may include `"transpose": true` flags. When a matrix is transposed, its rows/columns swap and its structural property transforms according to the `transpose_properties` table.

The reference specification at `/app/input/spec.json` documents the property algebra and cost model for cross-checking your inferred formulas.

For each chain, find the parenthesization that minimizes total FLOP cost. The cost of each multiplication depends on the structural properties of both operands (not just their dimensions), so a standard matrix chain DP is insufficient — you must track how properties propagate through intermediate results to compute costs correctly. The cost model has a priority-based hierarchy that must be discovered from the benchmark measurements.

Write the result to `/app/output/plans.json`:

```json
{
  "plans": {
    "<chain_id>": {
      "steps": [
        {
          "left": "<operand_name>",
          "right": "<operand_name>",
          "result": "<intermediate_name>",
          "result_properties": "<property_or_list>",
          "cost": <integer>
        }
      ],
      "total_cost": <integer>
    }
  }
}
```

Each step describes one matrix multiplication in execution order. The `left` and `right` fields reference either original matrix names or intermediate results from prior steps. Steps must multiply only contiguous subchains (preserving the original operand ordering). The `result_properties` field must reflect the correct propagated property. The `total_cost` is the sum of all step costs in the chain.