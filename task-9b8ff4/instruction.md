A steel mill cuts standard-width raw bars (stock width specified in the data) into smaller pieces per customer orders. The problem instance at `/app/data/problem.json` specifies the `stock_width` and 15 item types, each with a `width` and `demand`.

Find the minimum number of stock bars needed to satisfy all demands. Each bar can be cut into multiple pieces provided the total cut width does not exceed `stock_width`. With 15 item types the feasible pattern space is exponential — brute-force enumeration of all possible cutting patterns is computationally intractable.

Write a program that reads `/app/data/problem.json` and produces `/app/results.json` with this structure:

```json
{
  "total_rolls": <int>,
  "lp_bound": <float>,
  "patterns": [
    {"cuts": {"<width_as_string>": <count_in_pattern>, ...}, "count": <number_of_bars_using_this_pattern>},
    ...
  ]
}
```

- `total_rolls`: sum of all pattern counts — the total number of stock bars consumed
- `lp_bound`: a valid continuous (LP) relaxation lower bound on the minimum number of rolls
- `patterns`: each entry maps item widths to how many times they appear in the pattern, plus how many bars are cut with that pattern
- Every customer demand must be fully met (total production per width ≥ demand)
- No cutting pattern may exceed `stock_width`
- The solution must be provably near-optimal: `total_rolls ≤ ceil(lp_bound) + 1`
- All results must be computed by your code — do not hardcode answers