A logistics company must decide which candidate distribution centers to open and how to route shipments to customer regions. Demand is uncertain and modeled through multiple forecast scenarios. Each facility has a fixed opening cost and a maximum throughput constraint. Customer demand that cannot be fulfilled incurs a per-unit shortage penalty.

Data files describing the network are in `/app/data/`. No schema documentation is provided — explore the directory and inspect each file to determine the network structure, cost parameters, demand scenarios, and risk configuration.

Write your complete analysis to `/app/results.json` with the following structure:

```json
{
  "risk_neutral": {
    "objective_value": "<total optimal cost>",
    "facilities_open": ["<sorted 0-indexed facility IDs>"],
    "facility_cost": "<sum of opening costs of selected facilities>",
    "expected_second_stage_cost": "<probability-weighted recourse cost>",
    "scenario_costs": ["<per-scenario recourse costs>"]
  },
  "risk_averse": {
    "objective_value": "<risk-adjusted total cost>",
    "facilities_open": ["<sorted 0-indexed facility IDs>"],
    "facility_cost": "<float>",
    "expected_second_stage_cost": "<float>",
    "var_value": "<tail threshold>",
    "cvar_value": "<conditional tail expectation>",
    "scenario_costs": ["<per-scenario recourse costs>"]
  },
  "vss": "<float>",
  "evpi": "<float>"
}
```

- **risk_neutral**: Optimal first-stage facility selection minimizing total expected cost (opening costs plus probability-weighted operational costs including shipping and shortage penalties) across all demand scenarios.
- **risk_averse**: Optimal facility selection under a composite objective that blends expected cost with a tail-risk penalty, using the risk parameters found in the data. `var_value` is the optimal cost threshold separating normal from tail scenarios; `cvar_value` is the conditional expectation of recourse cost above that threshold.
- **vss**: The expected-cost penalty of ignoring demand variability — the gap between evaluating mean-demand facility decisions against the full scenario set and the true stochastic optimum.
- **evpi**: The savings from perfect demand foresight — the gap between the stochastic optimum and the weighted average of independently optimized per-scenario solutions.

All values are floats. `facilities_open` lists are sorted ascending.