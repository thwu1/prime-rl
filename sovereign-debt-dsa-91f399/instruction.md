Build a sovereign debt sustainability analysis engine at `/app/dsa_engine.py`. The environment provides macroeconomic projection data, a methodology reference, and configuration parameters.

**Inputs:**

- `/app/data/schema.sql` -- SQLite dump with a normalized relational schema. Country metadata in `countries` includes an `endogenous_rate` flag and a foreign-currency debt share. Macroeconomic projections are in `macro_variables` (EAV format -- one row per country/year/variable). The interest rate variable name differs across countries depending on whether rates are endogenous. Debt service flows are in `debt_service`. Stress shock magnitudes are in `stress_parameters` (EAV). One-off fiscal shocks are in `contingent_liabilities` and must be added to the stock-flow adjustment for the specified year.
- `/app/data/config.toml` -- Risk classification thresholds, stress scenario application rules, risk premium function parameters with convergence settings, consolidation search settings, and output formatting.
- `/app/docs/methodology.md` -- Debt dynamics framework: the accumulation identity, analytical decomposition, gross financing needs, debt-stabilizing balance, endogenous risk premium mechanism, and consolidation path concept.

**Required output:** `/app/output/results.json` -- JSON array of per-country objects:
```json
{
  "country_name": "",
  "baseline": {
    "debt_trajectory": [],
    "decomposition": [{"year": 0, "change_in_debt": 0.0, "real_interest_rate": 0.0, "real_growth": 0.0, "real_exchange_rate": 0.0, "relative_inflation": 0.0, "automatic_debt_dynamics": 0.0, "primary_balance_contribution": 0.0, "sfa": 0.0}],
    "gfn": [],
    "debt_stabilizing_pb": []
  },
  "stress": {"debt_trajectory": []},
  "risk_assessment": {
    "debt_stabilizes_baseline": true,
    "avg_gfn": 0.0,
    "terminal_debt": 0.0,
    "signal": ""
  },
  "convergence": {
    "iterations": 0,
    "risk_premium_applied": 0.0
  },
  "consolidation": {
    "required": false,
    "adjustment_pp": 0.0,
    "adjusted_terminal_debt": 0.0
  }
}
```

- `debt_trajectory`: initial debt followed by one projected value per year
- `convergence`: for endogenous-rate countries, iteration count until the trajectory stabilized and the uniform risk premium applied to all years. Non-endogenous countries: iterations=1, premium=0.0
- `consolidation`: for countries with `"high"` signal, the minimum constant primary balance adjustment (pp of GDP, to the search precision in config) that moves the signal to at most `"moderate"`. For non-high countries, required=false with zeros
- `signal`: `"high"`, `"moderate"`, or `"low"` per threshold rules in config
- All numerical values rounded per config precision

`/app/output/trajectories.png` -- gnuplot-generated PNG showing baseline and stressed debt-to-GDP trajectories for all countries with labeled axes and legend.

**Execution:** `python3 /app/dsa_engine.py`
