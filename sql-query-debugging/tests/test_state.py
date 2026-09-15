
"""
Tests for the cross-engine SQL debugging task.
Each test runs the agent's fixed query against the PostgreSQL database and
compares the result with the known-correct PG reference query output.
Also validates the audit report structure.
"""

import os
import json
import datetime
from decimal import Decimal

import psycopg2
import pytest

FIXED_DIR = '/app/fixed_queries'
AUDIT_PATH = '/app/audit_report.json'

# ---------------------------------------------------------------------------
# Correct reference queries (PostgreSQL-compatible)
# ---------------------------------------------------------------------------

CORRECT_Q1 = """
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

CORRECT_Q2 = """
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

CORRECT_Q3 = """
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

CORRECT_Q4 = """
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

CORRECT_Q5 = """
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

CORRECT_Q6 = """
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

CORRECT_Q7 = """
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

CORRECT_QUERIES = {
    1: CORRECT_Q1,
    2: CORRECT_Q2,
    3: CORRECT_Q3,
    4: CORRECT_Q4,
    5: CORRECT_Q5,
    6: CORRECT_Q6,
    7: CORRECT_Q7,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_pg_sql(sql):
    """Execute SQL against the PostgreSQL trading database and return rows."""
    conn = psycopg2.connect(dbname='trading', user='postgres')
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    conn.close()
    return rows


def read_fixed(n):
    """Read the agent's fixed query file."""
    path = os.path.join(FIXED_DIR, f'query_{n}.sql')
    assert os.path.isfile(path), (
        f"Expected fixed query at {path} but file does not exist"
    )
    with open(path) as f:
        content = f.read().strip()
    assert len(content) > 10, f"Fixed query {n} appears empty or trivially short"
    return content


def normalize(rows, float_decimals=2):
    """Normalize PG result types for stable comparison."""
    out = []
    for row in rows:
        normed = []
        for v in row:
            if isinstance(v, Decimal):
                normed.append(round(float(v), float_decimals))
            elif isinstance(v, float):
                normed.append(round(v, float_decimals))
            elif isinstance(v, (datetime.date, datetime.datetime)):
                normed.append(str(v))
            else:
                normed.append(v)
        out.append(tuple(normed))
    return out


# ---------------------------------------------------------------------------
# Tests -- Query 1: Desk P&L Summary
# ---------------------------------------------------------------------------

class TestQuery1:
    """Desk P&L Summary -- must filter active traders and settled trades."""

    def test_output_matches(self):
        expected = normalize(run_pg_sql(CORRECT_Q1))
        agent_sql = read_fixed(1)
        actual = normalize(run_pg_sql(agent_sql))
        assert len(actual) == len(expected), (
            f"Expected {len(expected)} rows, got {len(actual)}"
        )
        assert actual == expected, (
            f"Query 1 result mismatch.\nExpected: {expected}\nActual:   {actual}"
        )

    def test_row_count(self):
        """Should produce exactly 4 rows (one per desk with active traders)."""
        agent_sql = read_fixed(1)
        rows = run_pg_sql(agent_sql)
        assert len(rows) == 4, f"Expected 4 desk rows, got {len(rows)}"


# ---------------------------------------------------------------------------
# Tests -- Query 2: Settlement Anomaly Detection
# ---------------------------------------------------------------------------

class TestQuery2:
    """Settlement anomaly detection -- must use business-day T+2."""

    def test_output_matches(self):
        expected = normalize(run_pg_sql(CORRECT_Q2))
        agent_sql = read_fixed(2)
        actual = normalize(run_pg_sql(agent_sql))
        assert len(actual) == len(expected), (
            f"Expected {len(expected)} anomalies, got {len(actual)}"
        )
        expected_ids = {r[0] for r in expected}
        actual_ids = {r[0] for r in actual}
        assert actual_ids == expected_ids, (
            f"Anomaly trade IDs mismatch.\n"
            f"Expected: {sorted(expected_ids)}\n"
            f"Actual:   {sorted(actual_ids)}"
        )

    def test_no_null_settlements(self):
        """Cancelled/pending trades with NULL settlement must be excluded."""
        agent_sql = read_fixed(2)
        rows = run_pg_sql(agent_sql)
        for row in rows:
            assert row[4] is not None, (
                f"Trade {row[0]} has NULL settlement -- should be excluded"
            )


# ---------------------------------------------------------------------------
# Tests -- Query 3: VWAP
# ---------------------------------------------------------------------------

class TestQuery3:
    """VWAP -- must use weighted formula and exclude zero-volume days."""

    def test_output_matches(self):
        expected = normalize(run_pg_sql(CORRECT_Q3), float_decimals=4)
        agent_sql = read_fixed(3)
        actual = normalize(run_pg_sql(agent_sql), float_decimals=4)
        assert len(actual) == len(expected), (
            f"Expected {len(expected)} instruments, got {len(actual)}"
        )
        for exp_row, act_row in zip(expected, actual):
            assert exp_row[0] == act_row[0], (
                f"Symbol mismatch: expected {exp_row[0]}, got {act_row[0]}"
            )
            assert abs(exp_row[1] - act_row[1]) < 0.01, (
                f"VWAP mismatch for {exp_row[0]}: "
                f"expected {exp_row[1]}, got {act_row[1]}"
            )


# ---------------------------------------------------------------------------
# Tests -- Query 4: Risk Utilization
# ---------------------------------------------------------------------------

class TestQuery4:
    """Risk utilization -- must deduplicate limits, use settled trades, use ABS."""

    def test_output_matches(self):
        expected = normalize(run_pg_sql(CORRECT_Q4))
        agent_sql = read_fixed(4)
        actual = normalize(run_pg_sql(agent_sql))
        assert len(actual) == len(expected), (
            f"Expected {len(expected)} rows, got {len(actual)}"
        )
        exp_map = {r[0]: r for r in expected}
        act_map = {r[0]: r for r in actual}
        assert set(exp_map.keys()) == set(act_map.keys()), (
            f"Trader set mismatch.\n"
            f"Expected: {sorted(exp_map.keys())}\n"
            f"Actual:   {sorted(act_map.keys())}"
        )
        for name in exp_map:
            e = exp_map[name]
            a = act_map[name]
            assert e[2] == a[2], (
                f"{name}: asset_class mismatch: expected {e[2]}, got {a[2]}"
            )
            assert abs(e[5] - a[5]) < 0.05, (
                f"{name}: utilization mismatch: expected {e[5]}, got {a[5]}"
            )
            assert e[3] == a[3], (
                f"{name}: max_position mismatch: expected {e[3]}, got {a[3]}. "
                "Check risk limit deduplication."
            )

    def test_all_utilizations_positive(self):
        """All utilization percentages must be >= 0 (uses ABS)."""
        agent_sql = read_fixed(4)
        rows = run_pg_sql(agent_sql)
        for row in rows:
            v = float(row[5]) if isinstance(row[5], Decimal) else row[5]
            assert v >= 0, (
                f"Negative utilization for {row[0]}: {row[5]}. "
                "Ensure ABS() is applied to net position."
            )


# ---------------------------------------------------------------------------
# Tests -- Query 5: Trader Ranking by Region
# ---------------------------------------------------------------------------

class TestQuery5:
    """Trader ranking by region -- must partition by region, active only."""

    def test_output_matches(self):
        expected = normalize(run_pg_sql(CORRECT_Q5))
        agent_sql = read_fixed(5)
        actual = normalize(run_pg_sql(agent_sql))
        assert len(actual) == len(expected), (
            f"Expected {len(expected)} rows, got {len(actual)}"
        )
        exp_tuples = [(r[0], r[2], r[4]) for r in expected]
        act_tuples = [(r[0], r[2], r[4]) for r in actual]
        assert act_tuples == exp_tuples, (
            f"Ranking mismatch.\nExpected: {exp_tuples}\nActual:   {act_tuples}"
        )

    def test_no_inactive_traders(self):
        """Inactive traders must be excluded."""
        agent_sql = read_fixed(5)
        rows = run_pg_sql(agent_sql)
        names = {r[0] for r in rows}
        assert 'Frank Zhang' not in names, "Inactive trader Frank Zhang should be excluded"
        assert 'James Taylor' not in names, "Inactive trader James Taylor should be excluded"

    def test_pnl_values(self):
        """PnL values must match reference for each active trader."""
        expected = normalize(run_pg_sql(CORRECT_Q5))
        agent_sql = read_fixed(5)
        actual = normalize(run_pg_sql(agent_sql))
        exp_pnl = {r[0]: r[3] for r in expected}
        act_pnl = {r[0]: r[3] for r in actual}
        for name in exp_pnl:
            assert name in act_pnl, f"Missing trader {name} in output"
            assert abs(exp_pnl[name] - act_pnl[name]) < 0.05, (
                f"PnL mismatch for {name}: "
                f"expected {exp_pnl[name]}, got {act_pnl.get(name)}"
            )


# ---------------------------------------------------------------------------
# Tests -- Query 6: Seniority Performance
# ---------------------------------------------------------------------------

class TestQuery6:
    """Seniority performance -- must use fixed date, active-only, per-trader avg."""

    def test_output_matches(self):
        expected = normalize(run_pg_sql(CORRECT_Q6))
        agent_sql = read_fixed(6)
        actual = normalize(run_pg_sql(agent_sql))
        assert len(actual) == len(expected), (
            f"Expected {len(expected)} seniority bands, got {len(actual)}"
        )
        for exp_row, act_row in zip(expected, actual):
            assert exp_row[0] == act_row[0], (
                f"Seniority band mismatch: expected {exp_row[0]}, got {act_row[0]}"
            )
            assert exp_row[1] == act_row[1], (
                f"{exp_row[0]}: trader_count mismatch: "
                f"expected {exp_row[1]}, got {act_row[1]}"
            )
            assert abs(exp_row[2] - act_row[2]) < 0.05, (
                f"{exp_row[0]}: avg_pnl mismatch: "
                f"expected {exp_row[2]}, got {act_row[2]}"
            )
            assert exp_row[3] == act_row[3], (
                f"{exp_row[0]}: total_trades mismatch: "
                f"expected {exp_row[3]}, got {act_row[3]}"
            )

    def test_three_bands(self):
        """Should produce exactly 3 rows (Junior, Mid, Senior)."""
        agent_sql = read_fixed(6)
        rows = run_pg_sql(agent_sql)
        assert len(rows) == 3, f"Expected 3 seniority bands, got {len(rows)}"
        bands = {r[0] for r in rows}
        assert bands == {'Junior', 'Mid', 'Senior'}, (
            f"Expected Junior/Mid/Senior, got {bands}"
        )

    def test_seniority_as_of_q1_end(self):
        """Seniority must be calculated as of 2024-03-31, not current date."""
        agent_sql = read_fixed(6)
        rows = run_pg_sql(agent_sql)
        band_counts = {r[0]: int(r[1]) for r in rows}
        assert band_counts.get('Senior') == 2, (
            f"Senior trader count should be 2, got {band_counts.get('Senior')}. "
            "Check seniority reference date."
        )
        assert band_counts.get('Mid') == 3, (
            f"Mid trader count should be 3, got {band_counts.get('Mid')}. "
            "Check seniority reference date."
        )
        assert band_counts.get('Junior') == 3, (
            f"Junior trader count should be 3, got {band_counts.get('Junior')}. "
            "Check seniority reference date."
        )


# ---------------------------------------------------------------------------
# Tests -- Query 7: Position Valuation
# ---------------------------------------------------------------------------

class TestQuery7:
    """Position valuation -- must use valid prices, active traders, settled trades."""

    def test_output_matches(self):
        expected = normalize(run_pg_sql(CORRECT_Q7))
        agent_sql = read_fixed(7)
        actual = normalize(run_pg_sql(agent_sql))
        assert len(actual) == len(expected), (
            f"Expected {len(expected)} rows, got {len(actual)}"
        )
        exp_map = {(r[0], r[1]): r for r in expected}
        act_map = {(r[0], r[1]): r for r in actual}
        assert set(exp_map.keys()) == set(act_map.keys()), (
            f"Position set mismatch.\n"
            f"Expected: {sorted(exp_map.keys())}\n"
            f"Actual:   {sorted(act_map.keys())}"
        )
        for key in exp_map:
            e = exp_map[key]
            a = act_map[key]
            assert e[2] == a[2], (
                f"{key}: position mismatch: expected {e[2]}, got {a[2]}"
            )
            assert abs(e[3] - a[3]) < 0.05, (
                f"{key}: market_value mismatch: expected {e[3]}, got {a[3]}"
            )

    def test_no_inactive_traders(self):
        """Inactive traders must be excluded."""
        agent_sql = read_fixed(7)
        rows = run_pg_sql(agent_sql)
        names = {r[0] for r in rows}
        assert 'Frank Zhang' not in names, (
            "Inactive trader Frank Zhang should be excluded"
        )
        assert 'James Taylor' not in names, (
            "Inactive trader James Taylor should be excluded"
        )

    def test_valid_prices_only(self):
        """Market values must use prices from days with volume > 0."""
        agent_sql = read_fixed(7)
        actual = run_pg_sql(agent_sql)
        expected = run_pg_sql(CORRECT_Q7)
        exp_map = {(r[0], r[1]): float(r[3]) if isinstance(r[3], Decimal) else r[3]
                   for r in expected}
        act_map = {(r[0], r[1]): float(r[3]) if isinstance(r[3], Decimal) else r[3]
                   for r in actual}
        for key in exp_map:
            if key[1] in ('AAPL', 'MSFT'):
                assert key in act_map, f"Missing position {key}"
                assert abs(exp_map[key] - act_map[key]) < 0.05, (
                    f"{key}: market_value uses wrong price -- "
                    f"expected {exp_map[key]}, got {act_map.get(key)}. "
                    "Check that zero-volume price entries are excluded."
                )

    def test_commission_handling(self):
        """NULL commissions should be treated as zero, not propagate as NULL."""
        agent_sql = read_fixed(7)
        rows = run_pg_sql(agent_sql)
        for row in rows:
            assert row[4] is not None, (
                f"NULL total_commission for {row[0]} {row[1]} -- "
                "use COALESCE on commission"
            )


# ---------------------------------------------------------------------------
# Tests -- Audit Report
# ---------------------------------------------------------------------------

class TestAuditReport:
    """Validate the structured audit report."""

    def test_exists(self):
        assert os.path.isfile(AUDIT_PATH), (
            f"Audit report not found at {AUDIT_PATH}"
        )

    def test_valid_json(self):
        with open(AUDIT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, list), "Report must be a JSON array"

    def test_has_seven_entries(self):
        with open(AUDIT_PATH) as f:
            data = json.load(f)
        assert len(data) == 7, f"Expected 7 entries, got {len(data)}"

    def test_all_query_ids(self):
        with open(AUDIT_PATH) as f:
            data = json.load(f)
        ids = {e['query_id'] for e in data}
        assert ids == {1, 2, 3, 4, 5, 6, 7}, (
            f"Expected query_ids 1-7, got {sorted(ids)}"
        )

    def test_entry_structure(self):
        with open(AUDIT_PATH) as f:
            data = json.load(f)
        for entry in data:
            qid = entry.get('query_id', '?')
            assert isinstance(entry.get('query_id'), int), (
                f"query_id must be integer, got {type(entry.get('query_id'))}"
            )
            assert isinstance(entry.get('bugs'), list), (
                f"Query {qid}: 'bugs' must be an array"
            )
            assert len(entry['bugs']) > 0, (
                f"Query {qid}: should have at least one bug documented"
            )
            for bug in entry['bugs']:
                assert isinstance(bug, str) and len(bug) > 5, (
                    f"Query {qid}: each bug must be a non-trivial string"
                )
            assert isinstance(entry.get('engine_differences'), str), (
                f"Query {qid}: 'engine_differences' must be a string"
            )
            assert isinstance(entry.get('fix_approach'), str), (
                f"Query {qid}: 'fix_approach' must be a string"
            )
            assert len(entry['fix_approach']) > 10, (
                f"Query {qid}: fix_approach too short"
            )
