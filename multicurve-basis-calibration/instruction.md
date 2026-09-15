A EUR multicurve interest rate calibrator at `/app/` reads market quotes from `/app/data/market_quotes.csv` and a swap portfolio from `/app/data/portfolio.csv`. The project is broken and incomplete — it has build failures and produces incorrect results when those are addressed. Fix all issues so that it compiles, runs, and writes correct output to `/app/results.json`.

The Java source files are under `/app/src/`, with a build script at `/app/build.sh`. The calibrator constructs three EUR interest rate curves by finding zero rates such that all calibration instrument present values are zero (valuation date 2015-11-20):

- `EUR-DSCON-OIS` — 14 nodes (1M to 30Y), from OIS swap quotes
- `EUR-EURIBOR6M-IRS` — 11 nodes, from 6M fixing, 6Mx12M FRA, and 2Y–30Y IRS quotes
- `EUR-EURIBOR3M-BS` — 12 nodes, from 3M fixing, 3Mx6M FRA, and 1Y–30Y basis swap quotes

After calibration, the system must price each portfolio swap and compute bucketed PV01 sensitivities against all three curves. Each row in `portfolio.csv` defines a swap (id, type, tenor, rate, notional).

**Required output** (`/app/results.json`):

```json
{
  "valuation_date": "2015-11-20",
  "curves": {
    "<curve-name>": {"times": [...], "zero_rates": [...], "discount_factors": [...]}
  },
  "instrument_pvs": {"<label>": <float>, ...},
  "portfolio": {
    "<swap-id>": {
      "pv": <float>,
      "pv01": {
        "<curve-name>": [<pv01_per_node>, ...]
      }
    }
  }
}
```

**Success criteria:**

- Every calibration instrument |PV| < 1e-6.
- Every portfolio swap PV within 0.01 of independent computation.
- Every PV01 entry within 0.5 of independent computation.
- All three curves, 37 instrument PVs, 5 portfolio entries with complete PV01 vectors present.
