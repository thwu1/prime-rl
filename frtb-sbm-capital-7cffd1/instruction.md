A JSON file at `/app/portfolio.json` contains pre-computed delta sensitivities across four FRTB risk classes (Equity, FX, GIRR, CSR non-securitisation) and equity default-risk positions. Regulatory parameter tables (TSV) and a text excerpt describing Basel d457 MAR21/MAR22 aggregation rules are under `/app/reg_tables/`.

Build `/app/run.sh` to compute the FRTB Standardised Approach SBM capital requirement (Basel d457, January 2019 revision). The script must produce two artifacts:

**`/app/parameters.db`** — a SQLite database containing:

- One table per regulatory TSV file under `/app/reg_tables/`, named by the file stem (e.g. `equity_risk_weights.tsv` → table `equity_risk_weights`). Column names must match the TSV headers exactly, and every data row must be present.
- Table **`audit_buckets`** with columns `risk_class TEXT, bucket_id TEXT, scenario TEXT, kb REAL, sb REAL` — one row per (risk-class, bucket, scenario) triple recording the within-bucket capital (`kb`) and net weighted sensitivity (`sb`) used in across-bucket aggregation.
- Table **`audit_scenarios`** with columns `risk_class TEXT, scenario TEXT, capital REAL` — one row per (risk-class, scenario) pair with the across-bucket aggregated delta capital.

**`/app/output/capital_report.json`**:

```json
{
  "delta": {
    "equity": {"medium": <float>, "high": <float>, "low": <float>},
    "fx": {"medium": <float>, "high": <float>, "low": <float>},
    "girr": {"medium": <float>, "high": <float>, "low": <float>},
    "csr_nonsec": {"medium": <float>, "high": <float>, "low": <float>}
  },
  "drc": {"equity": <float>},
  "scenario_totals": {"medium": <float>, "high": <float>, "low": <float>},
  "sbm_delta_capital": <float>,
  "total_capital": <float>
}
```

`delta.<rc>.<scenario>`: risk-class delta capital under that correlation scenario. `scenario_totals.<scenario>`: sum of the four delta risk classes. `sbm_delta_capital`: maximum across scenario totals. `drc.equity`: equity default-risk capital. `total_capital` = `sbm_delta_capital + drc.equity`.

The portfolio exercises: multiple buckets with hedged positions; special-aggregation buckets (equity bucket 11, CSR bucket 16); multi-currency GIRR with inflation and cross-currency basis risk factors; multi-dimensional CSR correlations (issuer × tenor × curve); and the specified-currency risk-weight reduction. Use `jq` to validate that the output JSON conforms to the schema before the script exits.

All monetary values in USD millions. Tolerance: ±0.5 per risk-class-scenario, ±1.5 for aggregates.
