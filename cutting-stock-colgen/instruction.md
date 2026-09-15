A paper mill's automated production planner crashed mid-run. The mill cuts large master rolls of stock material into smaller customer-ordered widths. Your task is to generate a new production plan that minimizes the total number of master rolls consumed while fulfilling all remaining outstanding demand.

Production data is organized under `/app/`. Explore the directory structure to locate all relevant information. You will need to:

- Determine the active stock material specification from the materials configuration
- Aggregate all current customer orders from order batch files
- Account for any orders that have been canceled
- Deduct items already produced in prior production runs before the crash

Not all files under `/app/` are relevant to the current planning problem — some contain archived or historical data.

Write your solution to `/app/output/solution.json`:

```json
{
  "objective": <int, total stock rolls used>,
  "patterns": [
    {"pattern": [<int>, ...], "count": <int>},
    ...
  ]
}
```

Each `pattern` is an integer array with one entry per distinct ordered width (sorted by decreasing width), giving the number of pieces of that width cut from a single stock roll. `count` is the number of stock rolls cut using that pattern. The total width of pieces in each pattern must not exceed the stock roll width. Total production across all patterns must meet or exceed remaining demand for every ordered width. The solution must be optimal — using the minimum possible number of rolls.