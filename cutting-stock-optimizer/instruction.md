A production facility cuts raw material stock rolls into smaller product pieces to fulfill customer orders. All operational data — stock roll specifications, product catalog, order backlog, and production history — is stored in a SQLite database at `/app/data/operations.db`.

Produce a minimum-total-cost cutting plan that satisfies all remaining demand and write it to `/app/results/solution.json`:

```json
{
  "total_cost": <float>,
  "cutting_plan": [
    {
      "stock_type": "<stock roll type ID>",
      "cuts": [<int>, ...],
      "num_rolls": <int>
    }
  ],
  "total_waste_mm": <int>
}
```

Field definitions:

- `total_cost`: sum of (unit\_cost × num\_rolls) across all plan entries
- Each `cutting_plan` entry represents `num_rolls` identical rolls of type `stock_type`, each cut according to `cuts` — a vector indexed by product in alphabetical order of product\_code, where element *i* gives the count of product *i* pieces cut per roll
- All `cuts` values must be non-negative integers; all `num_rolls` values must be positive integers
- `total_waste_mm`: total unused material across all cut rolls (sum over every roll of: stock roll width minus total width of cuts on that roll)