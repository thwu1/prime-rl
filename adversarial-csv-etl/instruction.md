A DuckDB database at `/app/warehouse.duckdb` contains a financial institution's operational data across six tables. No schema documentation exists — discover the structure yourself. Build an analytics pipeline that produces five outputs in `/app/output/`.

## Output 1: `/app/output/rapid_chains.parquet`

Detect rapid-fire transaction chains in the completed-transaction graph. A chain is a directed path where each hop's recipient account is the next hop's sender, consecutive hops occur within 60 minutes, and no account appears more than once. Report all chains with 3 or more hops, keeping only the longest extension from each distinct starting transaction.

Columns: `chain_id` (INTEGER, sequential from 1 ordered by chain start time), `origin_account` (INTEGER), `terminal_account` (INTEGER), `hop_count` (INTEGER), `total_amount` (DOUBLE), `chain_start` (TIMESTAMP), `chain_end` (TIMESTAMP).

## Output 2: `/app/output/portfolio_values.parquet`

Compute mark-to-market portfolio valuations. For each account with holdings, compute total portfolio value on each trading day present in the market data. When a symbol has no recorded price on a given day, use the most recent prior price. Only include (account, day) pairs where every held symbol has an available price (current or carried forward).

Columns: `account_id` (INTEGER), `trade_date` (DATE), `portfolio_value` (DOUBLE), `num_positions` (INTEGER).

## Output 3: `/app/output/risk_scores.parquet`

Score each account with at least 10 completed transactions (sent or received) on behavioral metrics:

- **velocity**: completed transactions per active day (days with at least one transaction)
- **variability**: coefficient of variation (stddev / mean) of completed transaction amounts involving the account
- **concentration**: Herfindahl-Hirschman Index of counterparty distribution — for each counterparty, compute its share of the account's total transaction count, sum the squared shares

Compute the population z-score of each metric across all scored accounts. Composite score = `0.3 * velocity_z + 0.3 * variability_z + 0.4 * concentration_z`.

Columns: `account_id` (INTEGER), `velocity` (DOUBLE), `variability` (DOUBLE), `concentration` (DOUBLE), `composite_score` (DOUBLE).

## Output 4: `/app/output/regional_flows.parquet`

Analyze cross-regional completed-transaction flows. Map each transaction's sender and receiver to their branch's region. For each ordered (source_region, dest_region) pair:

- **total_flow**: sum of amounts
- **txn_count**: number of transactions
- **avg_amount**: mean transaction amount
- **net_flow**: total_flow(A→B) minus total_flow(B→A); zero for self-pairs
- **hhi**: Herfindahl-Hirschman Index of branch-pair concentration within each corridor — each (source_branch, dest_branch) pair's share of the corridor's total flow, squared and summed

Columns: `source_region` (VARCHAR), `dest_region` (VARCHAR), `total_flow` (DOUBLE), `txn_count` (BIGINT), `avg_amount` (DOUBLE), `net_flow` (DOUBLE), `hhi` (DOUBLE). Ordered by source_region, dest_region.

## Output 5: `/app/output/summary.json`

```json
{
  "total_chains": <int>,
  "longest_chain_hops": <int>,
  "total_accounts_valued": <int>,
  "highest_risk_account_id": <int>,
  "top_flow_corridor": {"source": "<region>", "dest": "<region>", "volume": <float>}
}
```

Where `top_flow_corridor` is the highest total_flow corridor excluding self-pairs.

The output directory `/app/output/` exists. DuckDB is pre-installed.