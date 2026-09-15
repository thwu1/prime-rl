#!/usr/bin/env python3
"""
Write the correct PostgreSQL-compatible SQL queries to /app/fixed_queries/.
Each query fixes the semantic bugs and SQLite-specific syntax in the
corresponding /app/queries/query_N.sql.
Also generates the audit report at /app/audit_report.json.
"""

import json
import os

FIXED_DIR = '/app/fixed_queries'
os.makedirs(FIXED_DIR, exist_ok=True)

# -------------------------------------------------------------------------
# Query 1: Desk P&L Summary
# Bugs fixed:
#   - Added t.is_active = 1 filter (KB Rule 8)
#   - Added tr.status = 'settled' filter (KB Rule 2)
# PG changes:
#   - ROUND requires CAST to NUMERIC
# -------------------------------------------------------------------------
Q1 = """\
SELECT
    t.desk,
    ROUND(CAST(SUM(tr.quantity * tr.price * CASE tr.direction
        WHEN 'BUY' THEN -1 WHEN 'SELL' THEN 1 END)
        - SUM(COALESCE(tr.commission, 0)) AS NUMERIC), 2) AS total_pnl
FROM traders t
JOIN trades tr ON t.id = tr.trader_id
WHERE t.is_active = 1
  AND tr.status = 'settled'
  AND tr.trade_date >= '2024-01-01'
  AND tr.trade_date <= '2024-03-31'
GROUP BY t.desk
ORDER BY total_pnl DESC;
"""

# -------------------------------------------------------------------------
# Query 2: Settlement Anomaly Detection
# Bugs fixed:
#   - T+2 now uses business days: +2 cal days for Mon-Wed, +4 for Thu/Fri
#   - Removed "OR settlement_date IS NULL" clause
#   - Added tr.status = 'settled' filter
# PG changes:
#   - DATE() with modifiers -> date + integer arithmetic
#   - strftime('%w', ...) -> EXTRACT(DOW FROM ...)
# -------------------------------------------------------------------------
Q2 = """\
SELECT
    tr.id AS trade_id,
    t.name AS trader_name,
    i.symbol,
    tr.trade_date,
    tr.settlement_date,
    (tr.trade_date + CASE
        WHEN EXTRACT(DOW FROM tr.trade_date) IN (4, 5) THEN 4
        ELSE 2
    END) AS expected_settlement
FROM trades tr
JOIN traders t ON tr.trader_id = t.id
JOIN instruments i ON tr.instrument_id = i.id
WHERE tr.status = 'settled'
  AND tr.settlement_date != (tr.trade_date + CASE
        WHEN EXTRACT(DOW FROM tr.trade_date) IN (4, 5) THEN 4
        ELSE 2
    END)
ORDER BY tr.trade_date;
"""

# -------------------------------------------------------------------------
# Query 3: VWAP per Instrument (March 2024)
# Bugs fixed:
#   - Uses proper VWAP formula: SUM(close*volume)/SUM(volume) instead of AVG
#   - Filters out volume = 0 days (KB Rule 4)
# PG changes:
#   - ROUND requires CAST to NUMERIC
# -------------------------------------------------------------------------
Q3 = """\
SELECT
    i.symbol,
    ROUND(CAST(SUM(dp.close_price * dp.volume) AS NUMERIC) / SUM(dp.volume), 4) AS vwap
FROM daily_prices dp
JOIN instruments i ON dp.instrument_id = i.id
WHERE dp.price_date >= '2024-03-01'
  AND dp.price_date <= '2024-03-31'
  AND dp.volume > 0
GROUP BY i.symbol
ORDER BY i.symbol;
"""

# -------------------------------------------------------------------------
# Query 4: Risk Utilization Report
# Bugs fixed:
#   - Uses CTE to select most recent applicable risk limit (KB Rule 7)
#   - Filters trades to settled only (KB Rule 1)
#   - Uses ABS() on net position (KB Rule 6)
# PG changes:
#   - ROUND requires CAST to NUMERIC
# -------------------------------------------------------------------------
Q4 = """\
WITH latest_limits AS (
    SELECT
        trader_id,
        asset_class,
        max_position,
        ROW_NUMBER() OVER (
            PARTITION BY trader_id, asset_class
            ORDER BY effective_date DESC
        ) AS rn
    FROM risk_limits
    WHERE effective_date <= '2024-03-31'
      AND (expiry_date IS NULL OR expiry_date > '2024-03-31')
),
net_positions AS (
    SELECT
        tr.trader_id,
        i.asset_class,
        SUM(tr.quantity * CASE tr.direction WHEN 'BUY' THEN 1 WHEN 'SELL' THEN -1 END) AS net_qty
    FROM trades tr
    JOIN instruments i ON tr.instrument_id = i.id
    WHERE tr.status = 'settled'
    GROUP BY tr.trader_id, i.asset_class
)
SELECT
    t.name,
    t.desk,
    ll.asset_class,
    ll.max_position,
    COALESCE(np.net_qty, 0) AS net_position,
    ROUND(CAST(ABS(COALESCE(np.net_qty, 0)) * 100.0 / ll.max_position AS NUMERIC), 2) AS utilization_pct
FROM traders t
JOIN latest_limits ll ON t.id = ll.trader_id AND ll.rn = 1
LEFT JOIN net_positions np ON t.id = np.trader_id AND ll.asset_class = np.asset_class
WHERE t.is_active = 1
ORDER BY utilization_pct DESC;
"""

# -------------------------------------------------------------------------
# Query 5: Trader Performance Ranking by Region
# Bugs fixed:
#   - PARTITION BY t.region instead of t.desk
#   - Added t.is_active = 1 filter (KB Rule 8)
#   - Uses COALESCE on commission (KB Rule 10)
# PG changes:
#   - ROUND requires CAST to NUMERIC
# -------------------------------------------------------------------------
Q5 = """\
SELECT
    t.name,
    t.desk,
    t.region,
    ROUND(CAST(SUM(tr.quantity * tr.price * CASE tr.direction
        WHEN 'BUY' THEN -1 WHEN 'SELL' THEN 1 END)
        - SUM(COALESCE(tr.commission, 0)) AS NUMERIC), 2) AS pnl,
    RANK() OVER (PARTITION BY t.region ORDER BY
        SUM(tr.quantity * tr.price * CASE tr.direction
            WHEN 'BUY' THEN -1 WHEN 'SELL' THEN 1 END)
        - SUM(COALESCE(tr.commission, 0)) DESC
    ) AS region_rank
FROM traders t
JOIN trades tr ON t.id = tr.trader_id
WHERE tr.status = 'settled'
  AND t.is_active = 1
  AND tr.trade_date BETWEEN '2024-01-01' AND '2024-03-31'
GROUP BY t.id, t.name, t.desk, t.region
ORDER BY t.region, region_rank;
"""

# -------------------------------------------------------------------------
# Query 6: Trader Performance by Seniority Band
# Bugs fixed:
#   - Uses date subtraction instead of julianday('now') (KB Rule 5)
#   - Added t.is_active = 1 filter (KB Rule 8)
#   - Added tr.status = 'settled' filter (KB Rule 1/2)
#   - Computes per-trader P&L first via CTE, then averages (KB Rule 12)
#   - Uses COALESCE on commission (KB Rule 10)
# PG changes:
#   - julianday() -> ('2024-03-31'::date - hire_date) / 365.25
#   - ROUND requires CAST to NUMERIC
#   - COUNT/SUM results cast to INTEGER for consistent output
#   - GROUP BY 1 for CASE expression
# -------------------------------------------------------------------------
Q6 = """\
WITH trader_pnl AS (
    SELECT
        t.id AS trader_id,
        t.hire_date,
        ROUND(CAST(SUM(tr.quantity * tr.price * CASE tr.direction
            WHEN 'BUY' THEN -1 WHEN 'SELL' THEN 1 END)
            - SUM(COALESCE(tr.commission, 0)) AS NUMERIC), 2) AS pnl,
        COUNT(tr.id) AS trade_count
    FROM traders t
    JOIN trades tr ON t.id = tr.trader_id
    WHERE t.is_active = 1
      AND tr.status = 'settled'
      AND tr.trade_date BETWEEN '2024-01-01' AND '2024-03-31'
    GROUP BY t.id, t.hire_date
),
seniority_agg AS (
    SELECT
        CASE
            WHEN ('2024-03-31'::date - hire_date) / 365.25 < 3 THEN 'Junior'
            WHEN ('2024-03-31'::date - hire_date) / 365.25 <= 7 THEN 'Mid'
            ELSE 'Senior'
        END AS seniority,
        COUNT(*)::INTEGER AS trader_count,
        ROUND(CAST(SUM(pnl) / COUNT(*) AS NUMERIC), 2) AS avg_pnl_per_trader,
        SUM(trade_count)::INTEGER AS total_trades
    FROM trader_pnl
    GROUP BY 1
)
SELECT seniority, trader_count, avg_pnl_per_trader, total_trades
FROM seniority_agg
ORDER BY CASE seniority WHEN 'Senior' THEN 1 WHEN 'Mid' THEN 2 ELSE 3 END;
"""

# -------------------------------------------------------------------------
# Query 7: End-of-Quarter Position Valuation
# Bugs fixed:
#   - Added t.is_active = 1 filter (KB Rule 8)
#   - Added tr.status = 'settled' filter (KB Rule 1)
#   - Latest price filters volume > 0 (KB Rule 11)
#   - Uses COALESCE on commission (KB Rule 10)
#   - Uses CTEs for clean decomposition and correct aggregation
# PG changes:
#   - ROUND requires CAST to NUMERIC
# -------------------------------------------------------------------------
Q7 = """\
WITH latest_prices AS (
    SELECT
        instrument_id,
        close_price,
        ROW_NUMBER() OVER (PARTITION BY instrument_id ORDER BY price_date DESC) AS rn
    FROM daily_prices
    WHERE volume > 0
),
positions AS (
    SELECT
        tr.trader_id,
        tr.instrument_id,
        SUM(tr.quantity * CASE tr.direction WHEN 'BUY' THEN 1 WHEN 'SELL' THEN -1 END) AS net_qty,
        SUM(COALESCE(tr.commission, 0)) AS total_commission
    FROM trades tr
    WHERE tr.status = 'settled'
    GROUP BY tr.trader_id, tr.instrument_id
    HAVING SUM(tr.quantity * CASE tr.direction WHEN 'BUY' THEN 1 WHEN 'SELL' THEN -1 END) != 0
)
SELECT
    t.name,
    i.symbol,
    p.net_qty AS position,
    ROUND(CAST(p.net_qty * lp.close_price AS NUMERIC), 2) AS market_value,
    ROUND(CAST(p.total_commission AS NUMERIC), 2) AS total_commission
FROM traders t
JOIN positions p ON t.id = p.trader_id
JOIN instruments i ON p.instrument_id = i.id
JOIN latest_prices lp ON p.instrument_id = lp.instrument_id AND lp.rn = 1
WHERE t.is_active = 1
ORDER BY t.name, i.symbol;
"""

queries = {1: Q1, 2: Q2, 3: Q3, 4: Q4, 5: Q5, 6: Q6, 7: Q7}

for n, sql in queries.items():
    path = os.path.join(FIXED_DIR, f'query_{n}.sql')
    with open(path, 'w') as f:
        f.write(sql.strip() + '\n')
    print(f"Wrote {path}")

# -------------------------------------------------------------------------
# Audit Report
# -------------------------------------------------------------------------
audit_report = [
    {
        "query_id": 1,
        "bugs": [
            "Missing WHERE filter for active traders (is_active = 1) — includes inactive traders Frank Zhang and James Taylor in desk P&L",
            "Missing WHERE filter for settled trades (status = 'settled') — includes cancelled and pending trades in P&L calculation"
        ],
        "engine_differences": "PostgreSQL ROUND() requires NUMERIC type input for two-argument form, unlike SQLite which accepts any numeric. Fixed with CAST(... AS NUMERIC).",
        "fix_approach": "Added WHERE t.is_active = 1 AND tr.status = 'settled' filters per KB Rules 8 and 2. Wrapped ROUND argument in CAST(... AS NUMERIC) for PG compatibility."
    },
    {
        "query_id": 2,
        "bugs": [
            "Uses calendar +2 days instead of business-day T+2 — Thursday/Friday trades should skip weekends (+4 calendar days)",
            "Includes cancelled/pending trades with NULL settlement_date via OR IS NULL clause",
            "Missing settled-only filter — only settled trades have meaningful settlement dates"
        ],
        "engine_differences": "SQLite uses DATE(d, '+N days') and strftime('%w', d) for date arithmetic and day-of-week. PostgreSQL uses date + integer for adding days and EXTRACT(DOW FROM d) for day-of-week. Both use 0=Sunday through 6=Saturday convention.",
        "fix_approach": "Replaced DATE() with date+integer arithmetic, strftime with EXTRACT(DOW FROM). Added CASE for Thu(4)/Fri(5) → +4 days else +2 days. Removed OR IS NULL, added status='settled' filter."
    },
    {
        "query_id": 3,
        "bugs": [
            "Uses simple AVG(close_price) instead of volume-weighted average SUM(close*volume)/SUM(volume) per KB Rule 4",
            "Does not exclude zero-volume days which represent data gaps, distorting the average"
        ],
        "engine_differences": "PostgreSQL ROUND() requires NUMERIC cast. SQLite's CAST(... AS REAL) maps to PG's DOUBLE PRECISION, but ROUND needs NUMERIC specifically.",
        "fix_approach": "Replaced AVG with SUM(close_price * volume) / SUM(volume) VWAP formula. Added WHERE dp.volume > 0 filter. Used CAST(... AS NUMERIC) for ROUND compatibility."
    },
    {
        "query_id": 4,
        "bugs": [
            "Direct JOIN on risk_limits without deduplication — causes row multiplication when multiple limits exist for same (trader, asset_class)",
            "Missing settled-only filter on trades — includes cancelled/pending in position calculation",
            "Missing ABS() on net position — short positions show negative utilization instead of absolute risk consumption",
            "No filtering for expired risk limits — uses expired limits alongside current ones"
        ],
        "engine_differences": "ROW_NUMBER() window function and CTE syntax are standard SQL and work identically on both engines. ROUND requires NUMERIC cast in PG.",
        "fix_approach": "Restructured into two CTEs: latest_limits (deduplicates via ROW_NUMBER with expiry filtering per KB Rule 7) and net_positions (settled-only per KB Rule 1). Applied ABS() per KB Rule 6. CAST for PG ROUND."
    },
    {
        "query_id": 5,
        "bugs": [
            "PARTITION BY t.desk instead of t.region — ranks traders within desk instead of within region as specified",
            "Missing is_active filter — includes inactive traders in rankings",
            "Uses SUM(tr.commission) without COALESCE — NULL commissions propagate and corrupt P&L"
        ],
        "engine_differences": "RANK() returns BIGINT in PostgreSQL vs INTEGER in SQLite. Both support PARTITION BY and ORDER BY in window functions identically. ROUND needs NUMERIC cast in PG.",
        "fix_approach": "Changed PARTITION BY to t.region. Added WHERE t.is_active = 1. Wrapped commission in COALESCE(..., 0). Applied NUMERIC cast for ROUND."
    },
    {
        "query_id": 6,
        "bugs": [
            "Uses julianday('now') for seniority — produces wrong bands when run after 2024, should use fixed date 2024-03-31 per KB Rule 5",
            "Missing is_active filter — includes inactive traders in seniority analysis",
            "Missing settled-only filter — includes all trade statuses",
            "Computes AVG at trade level instead of per-trader level — traders with more trades are over-weighted per KB Rule 12",
            "Missing COALESCE on commission — NULL commissions corrupt the per-trade average"
        ],
        "engine_differences": "SQLite julianday() has no PostgreSQL equivalent. PG uses date subtraction (date - date returns integer days) divided by 365.25. SQLite allows GROUP BY column aliases; PG requires GROUP BY expression or ordinal position (GROUP BY 1).",
        "fix_approach": "CTE computes per-trader P&L first (KB Rule 12), then outer query groups by seniority. Replaced julianday with ('2024-03-31'::date - hire_date) / 365.25. Used GROUP BY 1 for PG compatibility. Added all required filters."
    },
    {
        "query_id": 7,
        "bugs": [
            "Latest price subquery uses MAX(price_date) without filtering volume > 0 — picks up zero-volume data gap entries per KB Rule 11",
            "Missing is_active filter — includes inactive traders",
            "Missing settled-only filter — includes cancelled/pending trades",
            "SUM(tr.commission) without COALESCE — NULL commissions produce NULL total_commission",
            "Direct JOIN approach causes incorrect aggregation — does not properly handle net positions"
        ],
        "engine_differences": "Both engines support CTEs and ROW_NUMBER window functions identically. The main PG difference is ROUND requiring NUMERIC cast. Subquery approach with MAX() works on both, but CTE with ROW_NUMBER is cleaner.",
        "fix_approach": "Restructured into two CTEs: latest_prices (ROW_NUMBER with volume > 0 filter per KB Rule 11) and positions (settled-only with COALESCE and HAVING for non-zero). Added is_active filter. Applied NUMERIC casts for PG ROUND."
    }
]

report_path = '/app/audit_report.json'
with open(report_path, 'w') as f:
    json.dump(audit_report, f, indent=2)
print(f"Wrote {report_path}")
