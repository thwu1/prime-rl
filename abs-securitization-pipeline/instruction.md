Build `/app/abs_pipeline.py` that produces analytics from SEC EDGAR ABS-EE loan-level asset data for Santander Drive Auto Receivables Trust 2026-1.

**Pre-populated at `/app/`:**
- `trust_config.json` — trust identification (depositor CIK, asset type prefix, collection period ending 2026-05-31, original pool balance and loan count)
- `tranche_structure.json` — note class details (beginning balances, coupon rates, day-count conventions, and actual calendar days where applicable)

The pipeline must produce three JSON files in `/app/output/` with analytics derived from the trust's ABS-EE filing on SEC EDGAR for the specified collection period. The EX-102 exhibit contains the loan-level XML asset data. SEC EDGAR APIs require a descriptive `User-Agent` header including a contact email. Asset data files may exceed 100 MB.

A loan is **active** if its end-of-period balance is greater than zero.

**`pool_summary.json`:**
- `pool_balance`: aggregate end-of-period balance of active loans (2 decimal places)
- `pool_factor`: pool_balance / original_pool_balance (6 decimal places)
- `wac_pct`: balance-weighted average coupon rate of active loans, as a percentage (2 decimal places)
- `wart_months`: balance-weighted average remaining term to maturity of active loans, in months (2 decimal places)
- `active_loan_count`: integer

**`delinquency.json`:**
`buckets` array for three delinquency ranges: 31–60, 61–90, and 91–120 days past due. Each entry: `label`, `min_days`, `max_days`, `units` (count of active delinquent loans in range), `dollars` (sum of their end balances, 2 decimal places), `pct` (dollars as a share of pool_balance, as a percentage, 2 decimal places).

**`tranche_interest.json`:**
`tranches` array with an entry per note class. Each entry: `class`, `interest` (accrued interest computed per the tranche's specified day-count convention, 2 decimal places).

Invocable as: `python3 /app/abs_pipeline.py`
