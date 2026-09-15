Problem data is in `/app/instance.json`. It specifies two stock bar types (each with a width in cm and a per-bar cost in dollars) and six member types (each with a width in cm and a required quantity).

A cutting pattern defines how many of each member type to cut from a single stock bar; leftover material is wasted. Find a set of cutting patterns and their repetition counts that minimize total stock cost while fulfilling all member demands. Patterns may use either stock type, and the solver should choose the mix that minimizes cost.

The space of feasible cutting patterns grows combinatorially and is too large to enumerate for general instances. An efficient pattern-generation strategy driven by LP dual information is the standard technique for this class of problems.

Write results to `/app/results.json`:

```json
{
  "lp_bound": <exact optimal value of the LP relaxation (float)>,
  "total_cost": <optimal integer cost (int)>,
  "patterns": [
    {"stock_type": <0 or 1>, "cuts": [c0, c1, c2, c3, c4, c5], "count": <int>},
    ...
  ]
}
```

- `lp_bound`: the exact optimum of the continuous (LP) relaxation of the set-covering formulation — not a heuristic bound or the continuous area lower bound.
- `total_cost`: the minimum total cost achievable with integer pattern counts.
- Each entry in `patterns` gives a stock type index (0 = first type, 1 = second), a vector of cut counts per member type, and how many bars are cut with that pattern.