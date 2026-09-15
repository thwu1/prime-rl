A logistics company operates a network of 3 suppliers, 6 candidate distribution facilities, and 8 customer regions. The company must decide which facilities to open (a strategic decision made before demand is observed) and how to route products from suppliers through open facilities to customers (an operational decision that adapts to realized demand).

Historical data includes 100 demand scenario observations with associated probabilities. The company has observed that while their cost-minimizing plan performs well on average, it leads to severe cost spikes in the worst demand scenarios — some quarters see transport costs nearly double the average.

## Data

- `/app/data/network.json` — facility capacities, opening costs, and per-unit transport costs (inbound from suppliers, outbound to customers)
- `/app/data/demand_scenarios.csv` — 100 historical demand observations per customer region with associated probabilities
- `/app/data/config.json` — capital budget constraint and risk management parameters
- `/app/data/output_spec.json` — required output format specification

## Objective

Produce two network plans and a comparative analysis:

1. **Cost-minimizing plan**: Select facilities and routing to minimize total expected cost (facility opening costs + expected transport costs across scenarios), ignoring worst-case risk.

2. **Risk-aware plan**: Select facilities and routing that balances expected cost against worst-case cost exposure, using the risk parameters specified in `config.json`. The plan should control the average cost experienced in the worst-performing fraction of scenarios (governed by `tail_risk_confidence`).

Both plans must satisfy: all customer demand is met in every scenario, facility throughput stays within capacity (only open facilities can be used), supplier output stays within limits, and total facility opening cost stays within the capital budget. Flow conservation must hold at all facilities.

## Deliverable

Write results to `/app/results/analysis.json` conforming to the schema in `/app/data/output_spec.json`.