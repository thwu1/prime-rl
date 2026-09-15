Build `/app/mbs_analytics.py`:

```
python3 /app/mbs_analytics.py \
  --freddie-orig /data/origination.txt \
  --freddie-perf /data/performance.txt \
  --ginniemae-factors /data/ginniemae_factors.dat \
  --psa-speed 150 --projection-months 36
```

File formats and calculation methodology are in `/data/docs/`. Pool assignment: derive pool ID from each loan sequence number's vintage quarter per `/data/docs/freddie_mac_format.txt` field 19 (e.g., `F20Q10000001` belongs to pool `2020Q1`).

**`/app/output/mbs.db`** — SQLite database with tables:

- `freddie_origination`: `loan_seq`, `orig_upb`, `orig_rate`, `orig_term`, `state`, plus remaining origination fields
- `freddie_performance`: `loan_seq`, `period`, `cur_upb`, `dlq_status`, `loan_age`, `rem_months`, `zb_code`, `zb_date`, `cur_rate`, `mi_recoveries`, `net_sale_proceeds`, `non_mi_recoveries`, `expenses`, `zb_removal_upb`, `dlq_accrued_interest`, plus remaining fields
- `ginniemae_factors`: `pool_id`, `report_date`, `original_face`, `current_face`, `pool_factor`, `security_rate`, `wac`, `wam`, `wala`, `loan_count`
- `pool_metrics`: per pool/period — `pool_id`, `period`, `active_loans` (non-terminated loans with positive UPB only), `total_upb`, `pool_factor`, `wac` (decimal, e.g. 0.035 not 3.5), `wam`, `wala`, `dlq_30_count` (dlq_status=1), `dlq_60_count` (dlq_status=2), `dlq_90plus_count` (dlq_status>=3)
- `prepayment_detail`: starting from second reporting period — `pool_id`, `period`, `smm`, `cpr`, `implied_psa` (positive when smm > 0)
- `cross_agency_summary`: `pool_id`, `agency` (`FREDDIE` or `GINNIEMAE`), `total_upb`, `pool_factor`, `wac`, `wam`, `loan_count`. Must contain entries for both agencies.

Views (must be `CREATE VIEW`, not tables):

- `v_prepayment_momentum`: `pool_id`, `period`, `smm`, `prev_smm` (prior period's SMM within same pool, NULL for first period), `smm_acceleration` (smm minus prev_smm, NULL for first period)
- `v_factor_decline_rate`: `pool_id`, `report_date`, `pool_factor`, `prior_factor` (prior date's factor within same pool, NULL for first), `decline_rate` (prior_factor minus pool_factor, NULL for first), `avg_decline_3` (mean of decline_rate over current row and up to 2 preceding rows per pool, NULLs excluded from averaging)

**`/app/output/report.json`** keys:

- `pool_metrics`: dict by pool ID -> chronologically sorted per-period list. Keys: `period`, `active_loans`, `total_upb`, `pool_factor`, `wac` (decimal), `wam`, `wala`, `dlq_30_count`, `dlq_60_count`, `dlq_90plus_count`
- `prepayment`: dict by pool ID, from second period onward. Keys: `period`, `smm` (non-negative), `cpr`, `implied_psa`
- `losses`: list for involuntary terminations only (exclude loans with voluntary prepayment zero-balance codes). Keys: `loan_seq`, `zb_code`, `zb_date`, `zb_removal_upb`, `mi_recoveries`, `net_sale_proceeds`, `non_mi_recoveries`, `expenses`, `dlq_accrued_interest`, `computed_actual_loss`
- `cashflow_projection`: dict by pool ID -> `--projection-months` records, 1-indexed months. Keys: `month`, `beginning_upb`, `scheduled_principal`, `prepayment`, `total_principal`, `ending_upb`, `pool_factor`, `interest`. Invariants: beginning_upb of month N equals ending_upb of month N-1; total_principal = scheduled_principal + prepayment; ending_upb = beginning_upb - total_principal; pool factor monotonically decreasing; interest positive each month.
- `ginniemae_pools`: dict by pool ID -> chronologically sorted per-date list. Keys: `report_date`, `original_face`, `current_face`, `pool_factor`, `security_rate`, `wac`, `wam`, `wala`, `loan_count`

**`/app/output/validate.sql`** — executable: `sqlite3 /app/output/mbs.db < /app/output/validate.sql`. Each output line: `CHECK_NAME|PASS` or `CHECK_NAME|FAIL|detail`. Required checks (all must pass): `gm_factor_consistency`, `upb_non_negative`, `pool_factor_bounds`, `origination_upb_match`.

Monetary values: 2 decimal places. Rates and factors: 8 decimal places.
