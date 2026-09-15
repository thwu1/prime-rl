Build a Python CLI tool at `/app/simm_calc.py` that computes ISDA SIMM v2.5 initial margin from CRIF (Common Risk Interchange Format) CSV files.

**Environment:**

- `/app/create_params_db.py` generates `/app/simm_params.db`, a SQLite database containing all SIMM v2.5 calibration data: risk weights, tenor/bucket/cross-bucket correlations, concentration thresholds, and currency classifications across all six risk classes (IR, FX, CreditQ, CreditNonQ, Equity, Commodity).
- `/app/crif/` contains 25 CRIF CSV test files (e.g., `C1_crif.csv`) with columns: `ProductClass,RiskType,Qualifier,Bucket,Label1,Label2,Amount,AmountCurrency,AmountUSD`.

**CLI:** `python3 /app/simm_calc.py <crif_csv_path>`

**CSV output (stdout):** One header row followed by one data row:

```
SIMM Delta,SIMM Vega,SIMM Curvature,SIMM Base Corr,SIMM AddOn,SIMM Benchmark
```

- `SIMM Delta` — total delta margin summed across all risk classes and product classes.
- `SIMM Vega` — total vega margin summed across all risk classes and product classes.
- `SIMM Curvature` — total curvature margin summed across all risk classes and product classes.
- `SIMM Base Corr` — base correlation margin (CreditQ only).
- `SIMM AddOn` — add-on margins (fixed amounts, notional factors, product class multipliers).
- `SIMM Benchmark` — total SIMM margin: per-product-class risk-class-correlated aggregation summed across product classes, plus add-ons. Note this is not a simple sum of the component columns.
- All values are integers (no decimals). Zero-valued components output as `-`.
- Use the `AmountUSD` column from CRIF inputs. Calculation currency: USD.

**SQLite output:** Each invocation must also write results to `/app/simm_results.db`, table `margin_results`:

```sql
CREATE TABLE margin_results (
    id TEXT PRIMARY KEY,
    delta REAL, vega REAL, curvature REAL,
    base_corr REAL, addon REAL, benchmark REAL
);
```

`id` is the CRIF filename stem (`C1` from `C1_crif.csv`). Use INSERT OR REPLACE semantics. Successive invocations on different CRIFs must accumulate rows in the same database.

**Requirements:**

- All model parameters must be read from `/app/simm_params.db` at runtime. Do not hardcode calibration values.
- The calculator must produce correct results for all 25 CRIF files in `/app/crif/`, covering delta, vega, curvature, base correlation, and add-on margin types across all risk classes.
- The calculator must also handle novel CRIFs with arbitrary sensitivity amounts not found in the provided test files.
- Both individual component values and the benchmark total must be correct.

**Tolerance:** Results must match expected values within 0.5% relative error for values >= 1,000,000,000 and within 1 absolute unit otherwise.
