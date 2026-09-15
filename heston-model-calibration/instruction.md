A SQLite database at `/app/options.db` contains European call option pricing data collected from three external market data feeds. The database schema, table names, column names, and feed identifiers are not documented — explore the database using `sqlite3` to understand its structure.

Not all feeds provide reliable data. At least one feed contains prices that are systematically inconsistent with the others, reflecting different underlying model assumptions. Identify which feed(s) are anomalous and exclude them before performing the final calibration.

Calibrate a Heston stochastic volatility model to the option prices from the reliable (non-excluded) feeds only. The Heston dynamics are:

```
dS(t) = r S(t) dt + sqrt(v(t)) S(t) dW_1(t)
dv(t) = kappa (vbar - v(t)) dt + gamma sqrt(v(t)) dW_2(t)
dW_1 dW_2 = rho dt
```

Recover the five parameters: `kappa` (mean-reversion speed), `gamma` (vol-of-vol), `vbar` (long-run variance), `v0` (initial variance), `rho` (correlation).

Write the following output files:

**`/app/anomaly_report.json`** — JSON object with key `excluded_feeds`: a list of feed name strings identifying the feeds excluded as inconsistent. Only genuinely inconsistent feeds may be excluded; feeds with reliable prices must not appear in this list.

**`/app/calibrated_params.json`** — JSON object with keys `kappa`, `gamma`, `vbar`, `v0`, `rho` (all finite float values). Parameters must satisfy these bounds:
- `kappa` in (0.001, 20.0)
- `gamma` in (0.001, 3.0)
- `vbar` in (0.0001, 1.0)
- `v0` in (0.0001, 1.0)
- `rho` in (-0.999, 0.999)

**`/app/model_prices.json`** — JSON object mapping each maturity as a string key (e.g. `"0.25"`) to a list of model call prices (one per strike in ascending order, matching the strike grid discovered from the database). Must include an entry for every maturity present in the database, with the correct number of strikes per maturity. Each reported price must be consistent with an independently computed Heston price using the calibrated parameters: relative difference `|reported - independent| / max(|independent|, 1.0)` must be below 2%.

**`/app/iv_surface.json`** — JSON object with keys:
- `maturities`: list of maturity floats
- `strikes`: list of strike floats
- `implied_vols`: object mapping maturity string to list of Black-Scholes implied volatilities (one per strike)

All implied volatilities must be in the range (0, 1.5). For each maturity, the implied volatility at the lowest strike must exceed the implied volatility at the highest strike (negative skew, characteristic of equity options).

**Calibration quality**: for each (maturity, strike) pair from a non-excluded feed, the model price computed from calibrated parameters must satisfy:
- If the observed market price > 0.50: relative error < 5%
- If the observed market price <= 0.50: absolute error < 0.10