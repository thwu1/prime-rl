A manufacturing plant's production planning system is deployed at `/app/`. The system contains order records, material specifications, machine configuration, and demand adjustment logs that together define a one-dimensional cutting stock problem instance. Explore the environment to discover the data sources, understand their schema and relationships, and assemble the complete problem instance.

Determine the minimum number of stock rolls needed to fulfill all pending orders (with any recorded demand adjustments applied). Compute the optimal LP relaxation bound of the set-covering formulation (one variable per feasible cutting pattern, one demand constraint per item type requiring supply >= demand, minimize total rolls).

Write results to `/app/output/solution.json`:
```json
{
  "lp_bound": <float>,
  "num_rolls": <int>,
  "patterns": [
    {"pattern": [<int>, ...], "num_rolls": <int>}
  ]
}
```

- `lp_bound`: optimal LP relaxation objective value
- `num_rolls`: total stock rolls consumed (sum of all pattern `num_rolls`)
- Each `pattern` is a list of integer counts, one per distinct piece width (ordered by decreasing width); `sum(width[i] * pattern[i])` must not exceed the stock roll width
- All demands must be met: for each piece width, total supply across patterns >= demand
- The integer solution must use at most `ceil(lp_bound) + 2` rolls

Note: the number of feasible cutting patterns is combinatorially large — direct enumeration is not practical.