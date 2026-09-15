#!/usr/bin/env python3
"""Reference solution for the financial analytics pipeline."""

import json
import os

import duckdb

OUTPUT = "/app/output"
DB = "/app/warehouse.duckdb"
os.makedirs(OUTPUT, exist_ok=True)

con = duckdb.connect(DB)

# ===================================================================
# Output 1: Rapid Transaction Chains via recursive CTE
# ===================================================================
con.execute(f"""
    COPY (
        WITH RECURSIVE chain_paths AS (
            -- Base: every completed transaction is a potential chain start
            SELECT
                txn_id AS start_txn,
                from_account AS origin_account,
                to_account AS current_account,
                1 AS hop_count,
                amount AS total_amount,
                txn_time AS chain_start,
                txn_time AS last_time,
                [from_account, to_account] AS visited
            FROM transactions
            WHERE status = 'completed'

            UNION ALL

            -- Recursive: extend by one hop
            SELECT
                cp.start_txn,
                cp.origin_account,
                t.to_account,
                cp.hop_count + 1,
                cp.total_amount + t.amount,
                cp.chain_start,
                t.txn_time,
                list_append(cp.visited, t.to_account)
            FROM chain_paths cp
            JOIN transactions t
                ON t.from_account = cp.current_account
                AND t.status = 'completed'
                AND t.txn_time > cp.last_time
                AND t.txn_time <= cp.last_time + INTERVAL 60 MINUTE
                AND NOT list_contains(cp.visited, t.to_account)
            WHERE cp.hop_count < 10
        ),
        longest_per_start AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY start_txn ORDER BY hop_count DESC
                ) AS rn
            FROM chain_paths
            WHERE hop_count >= 3
        )
        SELECT
            ROW_NUMBER() OVER (ORDER BY chain_start, origin_account)
                AS chain_id,
            origin_account,
            current_account AS terminal_account,
            hop_count,
            total_amount,
            chain_start,
            last_time AS chain_end
        FROM longest_per_start
        WHERE rn = 1
    ) TO '{OUTPUT}/rapid_chains.parquet' (FORMAT PARQUET)
""")
print("rapid_chains.parquet created")

# ===================================================================
# Output 2: Portfolio valuations via ASOF JOIN
# ===================================================================
con.execute(f"""
    COPY (
        WITH trade_dates AS (
            SELECT DISTINCT price_date AS trade_date FROM market_data
        ),
        holding_dates AS (
            SELECT h.account_id, h.symbol, h.quantity, d.trade_date
            FROM holdings h
            CROSS JOIN trade_dates d
        ),
        valued AS (
            SELECT
                hd.account_id, hd.trade_date, hd.symbol,
                hd.quantity,
                md.close_price,
                hd.quantity * md.close_price AS position_value
            FROM holding_dates hd
            ASOF JOIN market_data md
                ON hd.symbol = md.symbol
                AND hd.trade_date >= md.price_date
        ),
        complete_days AS (
            SELECT
                account_id, trade_date,
                SUM(position_value) AS portfolio_value,
                COUNT(*) AS num_positions
            FROM valued
            WHERE close_price IS NOT NULL
            GROUP BY account_id, trade_date
        ),
        expected_pos AS (
            SELECT account_id, COUNT(*) AS expected
            FROM holdings GROUP BY account_id
        )
        SELECT cd.account_id, cd.trade_date,
               cd.portfolio_value, cd.num_positions
        FROM complete_days cd
        JOIN expected_pos ep ON cd.account_id = ep.account_id
        WHERE cd.num_positions = ep.expected
        ORDER BY cd.account_id, cd.trade_date
    ) TO '{OUTPUT}/portfolio_values.parquet' (FORMAT PARQUET)
""")
print("portfolio_values.parquet created")

# ===================================================================
# Output 3: Behavioral risk scores via window functions
# ===================================================================
con.execute(f"""
    COPY (
        WITH all_txns AS (
            SELECT from_account AS account_id, to_account AS counterparty,
                   amount, CAST(txn_time AS DATE) AS txn_date
            FROM transactions WHERE status = 'completed'
            UNION ALL
            SELECT to_account, from_account, amount, CAST(txn_time AS DATE)
            FROM transactions WHERE status = 'completed'
        ),
        qualified AS (
            SELECT account_id
            FROM all_txns GROUP BY account_id HAVING COUNT(*) >= 10
        ),
        velocity_calc AS (
            SELECT a.account_id,
                   CAST(COUNT(*) AS DOUBLE) / COUNT(DISTINCT a.txn_date)
                       AS velocity
            FROM all_txns a
            WHERE a.account_id IN (SELECT account_id FROM qualified)
            GROUP BY a.account_id
        ),
        variability_calc AS (
            SELECT a.account_id,
                   STDDEV_SAMP(a.amount) / AVG(a.amount) AS variability
            FROM all_txns a
            WHERE a.account_id IN (SELECT account_id FROM qualified)
            GROUP BY a.account_id
        ),
        cp_counts AS (
            SELECT a.account_id, a.counterparty, COUNT(*) AS cnt
            FROM all_txns a
            WHERE a.account_id IN (SELECT account_id FROM qualified)
            GROUP BY a.account_id, a.counterparty
        ),
        acct_totals AS (
            SELECT account_id, SUM(cnt) AS total
            FROM cp_counts GROUP BY account_id
        ),
        concentration_calc AS (
            SELECT cc.account_id,
                   SUM(POWER(CAST(cc.cnt AS DOUBLE) / at.total, 2))
                       AS concentration
            FROM cp_counts cc
            JOIN acct_totals at ON cc.account_id = at.account_id
            GROUP BY cc.account_id
        ),
        base_metrics AS (
            SELECT v.account_id, v.velocity,
                   va.variability, c.concentration
            FROM velocity_calc v
            JOIN variability_calc va ON v.account_id = va.account_id
            JOIN concentration_calc c ON v.account_id = c.account_id
        )
        SELECT
            account_id, velocity, variability, concentration,
            0.3 * (velocity - AVG(velocity) OVER ())
                / STDDEV(velocity) OVER ()
            + 0.3 * (variability - AVG(variability) OVER ())
                / STDDEV(variability) OVER ()
            + 0.4 * (concentration - AVG(concentration) OVER ())
                / STDDEV(concentration) OVER ()
            AS composite_score
        FROM base_metrics
        ORDER BY composite_score DESC
    ) TO '{OUTPUT}/risk_scores.parquet' (FORMAT PARQUET)
""")
print("risk_scores.parquet created")

# ===================================================================
# Output 4: Regional flow analysis
# ===================================================================
con.execute(f"""
    COPY (
        WITH txn_regions AS (
            SELECT
                b1.region AS source_region, b2.region AS dest_region,
                a1.branch_id AS source_branch, a2.branch_id AS dest_branch,
                t.amount
            FROM transactions t
            JOIN accounts a1 ON t.from_account = a1.account_id
            JOIN accounts a2 ON t.to_account = a2.account_id
            JOIN branches b1 ON a1.branch_id = b1.branch_id
            JOIN branches b2 ON a2.branch_id = b2.branch_id
            WHERE t.status = 'completed'
        ),
        corridor_agg AS (
            SELECT source_region, dest_region,
                   SUM(amount) AS total_flow,
                   COUNT(*)::BIGINT AS txn_count,
                   AVG(amount) AS avg_amount
            FROM txn_regions
            GROUP BY source_region, dest_region
        ),
        with_net AS (
            SELECT
                c1.source_region, c1.dest_region,
                c1.total_flow, c1.txn_count, c1.avg_amount,
                CASE WHEN c1.source_region = c1.dest_region THEN 0.0
                     ELSE c1.total_flow - COALESCE(c2.total_flow, 0.0)
                END AS net_flow
            FROM corridor_agg c1
            LEFT JOIN corridor_agg c2
                ON c1.source_region = c2.dest_region
                AND c1.dest_region = c2.source_region
        ),
        branch_flows AS (
            SELECT source_region, dest_region,
                   source_branch, dest_branch,
                   SUM(amount) AS bp_flow
            FROM txn_regions
            GROUP BY source_region, dest_region, source_branch, dest_branch
        ),
        corridor_tot AS (
            SELECT source_region, dest_region, SUM(bp_flow) AS ct
            FROM branch_flows GROUP BY source_region, dest_region
        ),
        hhi_calc AS (
            SELECT bf.source_region, bf.dest_region,
                   SUM(POWER(bf.bp_flow / ct.ct, 2)) AS hhi
            FROM branch_flows bf
            JOIN corridor_tot ct
                ON bf.source_region = ct.source_region
                AND bf.dest_region = ct.dest_region
            GROUP BY bf.source_region, bf.dest_region
        )
        SELECT wn.source_region, wn.dest_region,
               wn.total_flow, wn.txn_count, wn.avg_amount,
               wn.net_flow, h.hhi
        FROM with_net wn
        JOIN hhi_calc h
            ON wn.source_region = h.source_region
            AND wn.dest_region = h.dest_region
        ORDER BY wn.source_region, wn.dest_region
    ) TO '{OUTPUT}/regional_flows.parquet' (FORMAT PARQUET)
""")
print("regional_flows.parquet created")

# ===================================================================
# Output 5: Summary JSON
# ===================================================================
total_chains = con.execute(
    f"SELECT COUNT(*) FROM '{OUTPUT}/rapid_chains.parquet'"
).fetchone()[0]
longest_hops = con.execute(
    f"SELECT MAX(hop_count) FROM '{OUTPUT}/rapid_chains.parquet'"
).fetchone()[0]
total_valued = con.execute(
    f"SELECT COUNT(DISTINCT account_id) FROM '{OUTPUT}/portfolio_values.parquet'"
).fetchone()[0]
top_risk = con.execute(
    f"SELECT account_id FROM '{OUTPUT}/risk_scores.parquet' "
    f"ORDER BY composite_score DESC LIMIT 1"
).fetchone()[0]
top_corr = con.execute(
    f"SELECT source_region, dest_region, total_flow "
    f"FROM '{OUTPUT}/regional_flows.parquet' "
    f"WHERE source_region != dest_region "
    f"ORDER BY total_flow DESC LIMIT 1"
).fetchone()

summary = {
    "total_chains": total_chains,
    "longest_chain_hops": longest_hops,
    "total_accounts_valued": total_valued,
    "highest_risk_account_id": top_risk,
    "top_flow_corridor": {
        "source": top_corr[0],
        "dest": top_corr[1],
        "volume": round(top_corr[2], 2),
    },
}

with open(f"{OUTPUT}/summary.json", "w") as f:
    json.dump(summary, f, indent=2)
print("summary.json created")

con.close()
