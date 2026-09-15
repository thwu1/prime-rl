A buggy legacy pricer exists at `/app/legacy/pricer_v1.py`. Reference data and product specifications are under `/app/data/`.

Deliver `/app/pricer.py` (Python CLI) and `/app/Makefile` that together form a pricing pipeline producing a SQLite database and summary report.

**`pricer.py` CLI interface:**

`heston-call`: `--spot`, `--strike`, `--rate`, `--maturity`, `--v0`, `--theta`, `--kappa`, `--sigma`, `--rho`, `--div-yield` (default 0). Stdout: `{"price": <float>}`. Prices must match `/app/data/heston_reference.csv` within 5e-3 and remain stable for maturities 0.01–30 years.

`clean-corr`: `--input-file` (JSON 2D array), `--output-file` (write cleaned JSON 2D array). Stdout: `{"is_psd_before": <bool>, "is_psd_after": true, "max_abs_eigenvalue_change": <float>}`. Output must be a valid correlation matrix: PSD, unit diagonal, symmetric, elements in [-1, 1]. Already-PSD input passes through unchanged with zero change.

`autocallable`: `--config` (JSON file). Config schema:
```json
{"assets": [{"spot":…, "v0":…, "theta":…, "kappa":…, "sigma":…, "rho":…, "div_yield":…}],
 "correlation_matrix": [[…]], "observation_times": [...],
 "autocall_barrier":…, "coupon_barrier":…, "coupon_rate":…,
 "knock_in_barrier": float|null, "snowball": bool, "notional":…,
 "risk_free_rate":…, "n_paths": int, "n_steps_per_year": int, "seed": int}
```
Stdout: `{"price": float, "std_error": float, "autocall_prob": [float], "expected_coupon_count": float}`

Product payoff semantics are defined in `/app/data/termsheet.yaml`. The pricer must handle correlated multi-asset stochastic volatility paths and non-PSD correlation inputs.

**`/app/Makefile` pipeline — required targets and outcomes:**

- `db-init`: `/app/pricing.db` exists with tables `heston_results` (strike REAL, reference_price REAL, computed_price REAL, abs_error REAL) and `autocall_results` (config_name TEXT, price REAL, std_error REAL, autocall_prob_json TEXT, expected_coupon_count REAL).
- `calibrate` (depends on `db-init`): `heston_results` populated with one row per entry in `/app/data/heston_reference.csv`.
- `clean` (depends on `db-init`): `/app/data/correlation_cleaned.json` exists and is PSD.
- `price-note` (depends on `calibrate`, `clean`): `autocall_results` populated with pricing output for `/app/data/note_config.json`.
- `report` (depends on `price-note`): `/app/report.txt` exists containing max calibration error, mean calibration error, number of strikes calibrated, and each autocallable config's name and price.
- `all` (default): full pipeline in dependency order.

The Makefile must use both `jq` and `sqlite3`.
