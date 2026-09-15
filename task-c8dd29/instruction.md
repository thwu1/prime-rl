A reinsurance company requires a year-end reserve valuation for a block of fully discrete whole life insurance policies. The actuarial assumptions and portfolio data are distributed across several files and formats in `/data/`. No additional documentation is provided beyond the data files themselves — inspect them to determine schemas, formats, and contents.

## Data

- `/data/assumptions.tar.gz` — archived actuarial assumptions (mortality basis, valuation parameters)
- `/data/portfolio.db` — relational data (policies, expenses, treaty terms)

## Output

### `/app/results.json`

Per policy group (keyed by group code):

| Key | Value |
|---|---|
| `net_premium` | Net level annual premium |
| `gross_premium` | Gross level annual premium |
| `net_policy_value_10` | Prospective net premium reserve at the valuation duration |
| `gross_policy_value_10` | Prospective gross premium reserve at the valuation duration |
| `fpt_reserve_10` | Full Preliminary Term modified reserve at the valuation duration |
| `expense_reserve_10` | Expense reserve at the valuation duration |
| `retained_benefit` | Net retained benefit after surplus and quota-share reinsurance |
| `ceded_benefit` | Ceded benefit |
| `retained_reserve_per_policy` | Retained reserve per policy |
| `ceded_reserve_per_policy` | Ceded reserve per policy |

Portfolio-level aggregates (top-level keys):

| Key | Value |
|---|---|
| `portfolio_retained_reserve` | Aggregate retained reserve across all groups (in-force weighted) |
| `portfolio_ceded_reserve` | Aggregate ceded reserve |
| `portfolio_total_reserve` | Total portfolio reserve |

Premiums and reserves follow the equivalence principle. Reserves are allocated proportionally to the benefit split.

### `/app/summary.csv`

Columns: `group_code,issue_age,benefit,count,net_premium,net_pv_10,retained_reserve,ceded_reserve`

One data row per group. `retained_reserve` and `ceded_reserve` are group totals (per-policy value times in-force count).