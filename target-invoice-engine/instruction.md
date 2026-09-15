Build `/app/run_pipeline.sh`. When executed from `/app/`, it must produce all outputs specified below. The script must be executable and must invoke the `sqlite3` command-line tool.

**Pre-existing files** in `/app/`:

- `schema.sql` — SQLite table definitions
- `data/*.csv` — participant and volume data (each filename stem matches a table in the schema; all CSVs include a header row)
- `pricing_schedule.txt` — authoritative fee schedule defining all applicable rates, bands, brackets, and rounding conventions
- `reference_invoices.json` — reference invoice totals for reconciliation comparison

**Required outputs:**

`/app/billing.db` — SQLite database with every table from `schema.sql` populated from the corresponding CSV. Must also contain:

- View `v_billing_group_aggregate` with columns: `group_id`, `leader_id`, `total_payment_orders`, `member_count`.
- Table `fee_breakdown` with one row per participant. Columns: `participant_id`, `service`, `fixed_fee`, `transaction_fee`, `bic_fee`, `lt_fee`, `other_fee`, `total`. All monetary values to 2 decimal places; `total` must equal the sum of the other five monetary columns. Column semantics:
  - `fixed_fee`: monthly account fees (DCA, ASTA) and AS pricing-option fees
  - `transaction_fee`: per-order, CTO, settlement, and internal-settlement charges
  - `bic_fee`: BIC registration and authorised-account-user charges
  - `lt_fee`: cross-banking-group liquidity transfer charges
  - `other_fee`: AS Fixed Fee I and Fixed Fee II

`/app/invoices.json`:
```json
{"<participant_id>": {"total": <float_2dp>}, ...}
```

`/app/reconciliation.json`:
```json
{
  "discrepancies": [{"participant_id": "...", "computed": 0.00, "reference": 0.00, "delta": 0.00}],
  "matched": ["..."]
}
```
A participant is discrepant when `|computed − reference| > 0.01`. `delta = computed − reference`. Only participants present in the reference file are evaluated.

`/app/audit.csv` — CSV with column headers containing the `fee_breakdown` data, sorted by `participant_id`.

The pipeline must produce correct results for any valid dataset conforming to the schema.
