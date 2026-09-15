GlobalEd is a multi-country subscription education platform. Finance requires a 60-month consolidated revenue forecast that integrates IFRS 9 expected credit loss provisions with probability-weighted forward-looking scenarios, FX hedge accounting with prospective effectiveness testing, and present-value discounting using a bootstrapped zero-coupon yield curve.

The company's operational and regulatory data spans multiple systems and formats:

- **SQLite database** at `/app/model.db` — entity reference data, subscription tiers, base pricing, subscriber snapshots, and par bond rate market data. Contains both current and historical records; some tables (audit logs, churn analytics, historical rates, deprecated discount rates) are not forecast inputs.
- **CSV data files** in `/app/data/` — rate curve projections (wide-format), FX hedge contract book, credit loss provision rates, and seasonality adjustments (some records are inactive, superseded, or unapproved).
- **Parquet file** at `/app/data/hedge_valuations.parquet` — quarterly mark-to-market valuation data for each hedge contract, required for IFRS 9 hedge effectiveness assessment.
- **TOML configuration** at `/app/config/policy.toml` — pricing policy parameters, subscriber growth model, and revenue recognition rules.
- **IFRS regulatory framework** at `/app/config/ifrs_framework.json` — IFRS 9 parameters governing ECL scenario modeling, hedge effectiveness testing criteria, and yield curve discounting methodology. Contains both current and superseded parameter versions.
- **CFO quarterly memo** at `/app/docs/cfo_memo.md` — revenue computation waterfall, hedge accounting treatment, ECL provision application guidance, and NPV requirements.

The output schema at `/app/config/output_schema.json` defines the 18 required metrics.

Produce `/app/results.json` conforming to that schema. All monetary values in USD (2 decimal places). Subscriber counts, month indices, and hedge counts must be integers. The effective FX rate must have 4 decimal places. The weighted average ECL rate must have 6 decimal places.