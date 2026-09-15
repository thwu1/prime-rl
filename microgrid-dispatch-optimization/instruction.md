A stochastic microgrid dispatch problem is defined in `/app/data/microgrid_stochastic.json`. The dataset specifies a 48-hour planning horizon under 5 weather/demand scenarios, each with an assigned probability.

The microgrid comprises solar PV, wind turbines, a lithium-ion battery, a hydrogen electrolyzer, a hydrogen fuel cell, a hydrogen storage tank, and a bidirectional utility grid connection.

Formulate and solve a two-stage stochastic mixed-integer program:
- **First stage**: The electrolyzer commitment schedule (on/off per hour) must be determined before uncertainty is revealed and is therefore shared identically across all scenarios.
- **Second stage**: For each scenario, determine the cost-optimal hourly dispatch of all equipment.

The objective minimizes a risk-adjusted cost: `(1 − risk_weight) × E[cost] + risk_weight × CVaR_α(cost)` where `E[cost]` is the probability-weighted expected scenario cost and `CVaR_α` is the Conditional Value-at-Risk at confidence level α. Both parameters are in the data file's `risk_parameters` section.

Scenario cost includes hourly grid energy charges (imports minus export revenue at time-varying prices), a demand charge on the peak hourly grid import within that scenario, and a battery degradation penalty proportional to total charge plus discharge throughput.

The electrolyzer's hydrogen production is a piecewise-linear function of its electrical input, defined by breakpoints in `electrolyzer_pwl_input_kw` and `electrolyzer_pwl_output_kwh`. The electrolyzer must be committed ON to operate and is subject to minimum-uptime/downtime cycling constraints specified in the system parameters. When on, its input must lie within the range of the PWL breakpoints.

All other operational constraints follow from the system parameters and apply in every scenario independently: energy balance, battery SOC dynamics (charge efficiency, no discharge loss), hydrogen tank dynamics (fuel cell consumes H2 at inverse of its efficiency per unit output), grid import ramp rates, spinning reserve headroom, and end-of-horizon sustainability (final battery SOC and H2 level must be at least their initial values).

Additionally, compute the **Value of Stochastic Solution (VSS)**:
1. Solve the deterministic Expected Value (EV) problem: construct a single mean scenario by probability-weighting all scenario parameters, and solve the resulting deterministic dispatch (with no risk term).
2. Fix the EV solution's electrolyzer commitment schedule and re-dispatch optimally across all stochastic scenarios to obtain the EEV expected cost.
3. VSS = EEV expected cost − stochastic expected cost.

Write results to `/app/results/solution.json` with exactly these keys:
- `stochastic_objective` (float): optimal risk-adjusted objective value
- `expected_cost` (float): E[cost] under optimal stochastic policy
- `cvar_cost` (float): CVaR_α(cost) under optimal stochastic policy
- `var_cost` (float): Value-at-Risk (the VaR auxiliary variable in the CVaR formulation)
- `ev_objective` (float): optimal objective of the deterministic mean-scenario problem
- `eev_cost` (float): expected cost when using EV commitment stochastically
- `vss` (float): Value of Stochastic Solution
- `worst_scenario_cost` (float): highest scenario cost under stochastic policy
- `best_scenario_cost` (float): lowest scenario cost under stochastic policy
- `total_electrolyzer_on_hours` (int): number of committed ON hours in optimal schedule
- `expected_renewable_fraction` (float): probability-weighted fraction of total demand served directly by solar + wind