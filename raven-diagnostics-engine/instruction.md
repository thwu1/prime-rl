Build a C-Python diagnostic pipeline at `/app/` that computes hydrological time series metrics. Reference C++ source is at `/app/reference/Diagnostics.cpp` and `/app/reference/Diagnostics.h`; it cannot be compiled standalone (it depends on the full Raven framework). Your implementation must produce numerically identical results to the reference for all metrics and edge cases.

**Required artifacts:**

- `/app/diag_engine.c` — C source file.
- `/app/Makefile` — running `make -C /app build` must produce `/app/libdiag.so` (a shared library).
- `/app/raven_diag.py` — Python 3 CLI that uses `/app/libdiag.so` to compute metrics.

`/app/libdiag.so` must export these C-linkage symbols:

```c
void compute_baseweights(const double *obs, const double *mod, const double *wts,
    int has_wts, int n, double blank_val, double threshold,
    const char *comparison, double *out_bw);

double compute_metric(const char *name, int width,
    const double *obs, const double *mod, const double *bw,
    int n, double timestep, int start_year, int start_month, int start_day,
    double blank_val);
```

**CLI usage:** `python3 /app/raven_diag.py --config CONFIG.json --data DATA.csv`

**Config JSON schema:**
```json
{
  "metrics": [{"name": "METRIC_NAME"}, {"name": "SOME_METRIC", "width": 5}],
  "start_date": "YYYY-MM-DD", "timestep": 1.0,
  "blank_value": -1.2345, "threshold": 0.0, "comparison": "NONE"
}
```

**Data CSV (no header):** `index,observed,modeled[,weight]`

**Output:** A single JSON object to stdout mapping each requested metric name to its computed float value.

**Required metrics:** NASH_SUTCLIFFE, DAILY_NSE, NASH_SUTCLIFFE_DER, NASH_SUTCLIFFE_RUN, LOG_NASH, NSE4, FUZZY_NASH, RMSE, RMSE_DER, KLING_GUPTA, KGE_PRIME, DAILY_KGE, KLING_GUPTA_DER, KLING_GUPTA_DEVIATION, PCT_BIAS, ABS_PCT_BIAS, ABSERR, ABSERR_RUN, ABSMAX, PDIFF, PCT_PDIFF, ABS_PCT_PDIFF, TMVOL, TMVOL_MARE, RCOEF, NSC, RSR, R2, MBF, R4MS4E, RTRMSE, RABSERR, PERSINDEX, YEARS_OF_RECORD, SPEARMAN.

The C++ reference code is the sole source of truth for all numerical behavior, edge cases, and invalid-input handling.
