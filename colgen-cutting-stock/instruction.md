A paper manufacturing facility must cut standard stock rolls into smaller widths to fulfill a batch of customer orders. The raw data — stock roll specifications and order details — are stored under `/app/data/`. Explore these files to determine the available stock dimensions and the exact customer requirements.

Your objective: determine the minimum number of stock rolls needed to fulfill all orders and produce a valid cutting plan, together with a mathematical lower bound proving the solution's near-optimality.

Write the result to `/app/results/solution.json` with this exact schema:

    {
      "lower_bound": <float>,
      "integer_objective": <int>,
      "patterns": [
        {
          "cuts": {"<width_as_string>": <count>, ...},
          "quantity": <int>
        }
      ],
      "total_waste": <int>,
      "num_distinct_patterns": <int>,
      "optimization_iterations": <int>
    }

**Field constraints:**

- `lower_bound` (float): A mathematical lower bound on the minimum rolls required. Must be at least `total_demanded_area / roll_width` (the area relaxation bound). Must be strictly less than the naive upper bound (the roll count when each pattern uses only a single item type). Must not exceed `integer_objective`.

- `integer_objective` (int): Total stock rolls consumed by the cutting plan. Must be strictly less than the naive single-item-type upper bound. The gap `integer_objective - lower_bound` must not exceed 15.

- `patterns` (list): Cutting patterns actually used. Each entry has `cuts` (a map from item width as string key to count of pieces cut from one roll) and `quantity` (how many rolls are cut with this pattern). The total width of all cuts in each pattern must not exceed the stock roll width. Only include patterns with `quantity > 0` and cuts with `count > 0`. The sum of all `quantity` values must equal `integer_objective`. For every item width, the total produced quantity across all patterns must meet or exceed its ordered demand.

- `total_waste` (int): Total wasted material, computed as `integer_objective * roll_width - sum(width_i * demand_i)` across all item types. Must be non-negative.

- `num_distinct_patterns` (int): Total distinct cutting patterns explored during the optimization process. Must strictly exceed the number of distinct item widths in the order set.

- `optimization_iterations` (int): Number of iterative improvement steps performed to discover better cutting patterns. Must be at least 2.