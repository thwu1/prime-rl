A paper mill must cut large stock rolls into smaller widths to fulfill customer orders. Each stock roll has a fixed width. A cutting pattern specifies how many pieces of each ordered width to cut from a single roll; the remaining width is trim waste. Multiple rolls may be cut using the same pattern.

Production data is distributed across several sources under `/app/data/`:
- Customer orders (required piece widths and quantities) are in CSV files under `/app/data/orders/`
- Stock roll specifications are in a SQLite database at `/app/data/inventory/stock.db`
- Operational parameters are in `/app/data/config/cutting_params.json`

Refer to `/app/docs/cutting_operations.txt` for additional context on data layout and conventions.

**Objective:** Determine a set of cutting patterns and roll counts that fulfills all order quantities using the minimum total number of stock rolls. The solution must include a certified lower bound on the optimal roll count (the LP relaxation value of the cutting stock formulation) and the corresponding optimality gap as a percentage.

Write the solution to `/app/output/solution.json`:

```json
{
  "patterns": [
    {
      "items": {"<product_code>": <count>, ...},
      "width_used": <int>,
      "rolls": <int>
    }
  ],
  "total_rolls": <int>,
  "lp_relaxation_bound": <float>,
  "optimality_gap_pct": <float>,
  "total_waste_mm": <int>
}
```