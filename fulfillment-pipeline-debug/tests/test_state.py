"""Verification tests for the fulfillment analytics pipeline views.

Each test runs an independently-computed reference query against the raw
tables, then compares the results with the agent's view output.
"""

import pytest
import psycopg2


@pytest.fixture(scope="module")
def db():
    conn = psycopg2.connect(dbname="fulfillment_analytics", user="postgres")
    conn.autocommit = True
    yield conn
    conn.close()


# ====================================================================
# View 1: v_hierarchy_revenue
# ====================================================================

def test_hierarchy_revenue_exists(db):
    cur = db.cursor()
    cur.execute("SELECT * FROM v_hierarchy_revenue LIMIT 0")
    cols = {d[0] for d in cur.description}
    assert {"hub_name", "customer_tier", "total_revenue"} <= cols


def test_hierarchy_revenue_hub_names(db):
    """Revenue must be grouped by the three hub names, not individual warehouses."""
    cur = db.cursor()
    cur.execute("SELECT DISTINCT hub_name FROM v_hierarchy_revenue ORDER BY hub_name")
    hubs = [r[0] for r in cur.fetchall()]
    assert hubs == ["Hub_Alpha", "Hub_Beta", "Hub_Gamma"], (
        f"Expected exactly 3 hub names, got: {hubs}"
    )


def test_hierarchy_revenue_tiers_are_text(db):
    """customer_tier column must be TEXT type, not JSONB."""
    cur = db.cursor()
    cur.execute(
        "SELECT pg_typeof(customer_tier)::text FROM v_hierarchy_revenue LIMIT 1"
    )
    row = cur.fetchone()
    assert row is not None, "v_hierarchy_revenue returned no rows"
    assert row[0] == "text", f"customer_tier should be text type, got {row[0]}"


def test_hierarchy_revenue_values(db):
    """Revenue totals must match a reference recursive computation."""
    cur = db.cursor()
    ref = """
    WITH RECURSIVE wt AS (
        SELECT warehouse_id, warehouse_name AS hub_name
        FROM warehouses WHERE parent_id IS NULL
        UNION ALL
        SELECT w.warehouse_id, wt.hub_name
        FROM warehouses w JOIN wt ON w.parent_id = wt.warehouse_id
    )
    SELECT wt.hub_name, o.metadata->>'customer_tier' AS customer_tier,
           SUM(o.total_amount) AS total_revenue
    FROM wt JOIN orders o ON o.warehouse_id = wt.warehouse_id
    GROUP BY wt.hub_name, o.metadata->>'customer_tier'
    ORDER BY wt.hub_name, customer_tier
    """
    cur.execute(ref)
    expected = cur.fetchall()

    cur.execute(
        "SELECT hub_name, customer_tier, total_revenue "
        "FROM v_hierarchy_revenue ORDER BY hub_name, customer_tier"
    )
    actual = cur.fetchall()

    assert len(actual) == len(expected), (
        f"Row count mismatch: {len(actual)} vs {len(expected)}"
    )
    for a, e in zip(actual, expected):
        assert str(a[0]) == str(e[0]), f"Hub mismatch: {a[0]} vs {e[0]}"
        assert str(a[1]) == str(e[1]), f"Tier mismatch: {a[1]} vs {e[1]}"
        assert abs(float(a[2]) - float(e[2])) < 0.01, (
            f"Revenue mismatch for {e[0]}/{e[1]}: {a[2]} vs {e[2]}"
        )


# ====================================================================
# View 2: v_rolling_fulfillment
# ====================================================================

def test_rolling_fulfillment_exists(db):
    cur = db.cursor()
    cur.execute("SELECT * FROM v_rolling_fulfillment LIMIT 0")
    cols = {d[0] for d in cur.description}
    assert {"region", "calc_date", "rolling_rate"} <= cols


def test_rolling_fulfillment_values(db):
    """Rolling averages must use the delivered stage and a 7-day window."""
    cur = db.cursor()
    ref = """
    WITH daily_rates AS (
        SELECT w.region, DATE(oe.completed_at) AS completion_date,
               COUNT(CASE WHEN oe.status = 'completed' THEN 1 END)::NUMERIC /
                   NULLIF(COUNT(*)::NUMERIC, 0) AS daily_rate
        FROM order_events oe
        JOIN orders o ON o.order_id = oe.order_id
        JOIN warehouses w ON w.warehouse_id = o.warehouse_id
        WHERE oe.stage_id = 5
        GROUP BY w.region, DATE(oe.completed_at)
    )
    SELECT region, completion_date AS calc_date,
           AVG(daily_rate) OVER (
               PARTITION BY region ORDER BY completion_date
               ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
           ) AS rolling_rate
    FROM daily_rates
    ORDER BY region, calc_date
    """
    cur.execute(ref)
    expected = {(r[0], str(r[1])): float(r[2]) for r in cur.fetchall()}

    cur.execute(
        "SELECT region, calc_date, rolling_rate "
        "FROM v_rolling_fulfillment ORDER BY region, calc_date"
    )
    actual = {(r[0], str(r[1])): float(r[2]) for r in cur.fetchall()}

    assert len(actual) == len(expected), (
        f"Row count mismatch: {len(actual)} vs {len(expected)}"
    )
    mismatches = []
    for key in expected:
        if key not in actual:
            mismatches.append(f"Missing: {key}")
        elif abs(actual[key] - expected[key]) >= 0.0001:
            mismatches.append(
                f"{key}: {actual[key]:.6f} vs {expected[key]:.6f}"
            )
    assert not mismatches, f"Rolling rate mismatches: {mismatches[:10]}"


def test_rolling_fulfillment_uses_delivered_stage(db):
    """The view must use the delivered stage (stage_id=5), not any other."""
    cur = db.cursor()
    # Count rows from the view
    cur.execute("SELECT COUNT(*) FROM v_rolling_fulfillment")
    view_count = cur.fetchone()[0]

    # Count rows using the correct stage (delivered = stage_id 5)
    cur.execute("""
        SELECT COUNT(*) FROM (
            SELECT w.region, DATE(oe.completed_at) AS d
            FROM order_events oe
            JOIN orders o ON o.order_id = oe.order_id
            JOIN warehouses w ON w.warehouse_id = o.warehouse_id
            WHERE oe.stage_id = 5
            GROUP BY w.region, DATE(oe.completed_at)
        ) sq
    """)
    ref_count = cur.fetchone()[0]

    assert view_count == ref_count, (
        f"Row count {view_count} doesn't match delivered-stage count {ref_count}. "
        f"Check that the view filters on the correct stage_id."
    )


# ====================================================================
# View 3: v_stage_gaps
# ====================================================================

def test_stage_gaps_exists(db):
    cur = db.cursor()
    cur.execute("SELECT * FROM v_stage_gaps LIMIT 0")
    cols = {d[0] for d in cur.description}
    assert {"order_id", "warehouse_type", "missed_stages"} <= cols


def test_stage_gaps_values(db):
    """Gaps must be detected starting from stage_order 1, not the min observed."""
    cur = db.cursor()
    ref = """
    WITH osl AS (
        SELECT oe.order_id, fs.stage_order
        FROM order_events oe
        JOIN fulfillment_stages fs ON fs.stage_id = oe.stage_id
    ),
    omax AS (
        SELECT order_id, MAX(stage_order) AS max_stage FROM osl GROUP BY order_id
    ),
    expected AS (
        SELECT om.order_id, generate_series(1, om.max_stage) AS expected_stage
        FROM omax om
    ),
    missing AS (
        SELECT e.order_id, e.expected_stage
        FROM expected e
        LEFT JOIN osl ON osl.order_id = e.order_id
            AND osl.stage_order = e.expected_stage
        WHERE osl.order_id IS NULL
    )
    SELECT m.order_id, w.warehouse_type,
           ARRAY_AGG(m.expected_stage ORDER BY m.expected_stage) AS missed_stages
    FROM missing m
    JOIN orders o ON o.order_id = m.order_id
    JOIN warehouses w ON w.warehouse_id = o.warehouse_id
    GROUP BY m.order_id, w.warehouse_type
    ORDER BY m.order_id
    """
    cur.execute(ref)
    expected = {r[0]: (r[1], sorted(r[2])) for r in cur.fetchall()}

    cur.execute(
        "SELECT order_id, warehouse_type, missed_stages "
        "FROM v_stage_gaps ORDER BY order_id"
    )
    actual = {r[0]: (r[1], sorted(r[2])) for r in cur.fetchall()}

    assert len(actual) == len(expected), (
        f"Row count mismatch: {len(actual)} vs {len(expected)}"
    )
    for oid in expected:
        assert oid in actual, f"Missing order_id {oid} in v_stage_gaps"
        assert actual[oid][0] == expected[oid][0], (
            f"warehouse_type mismatch for order {oid}: "
            f"{actual[oid][0]} vs {expected[oid][0]}"
        )
        assert actual[oid][1] == expected[oid][1], (
            f"missed_stages mismatch for order {oid}: "
            f"{actual[oid][1]} vs {expected[oid][1]}"
        )


def test_stage_gaps_includes_stage1_skips(db):
    """Orders that skip stage 1 must still appear with stage 1 in missed_stages."""
    cur = db.cursor()
    cur.execute("""
        WITH osl AS (
            SELECT oe.order_id, fs.stage_order
            FROM order_events oe
            JOIN fulfillment_stages fs ON fs.stage_id = oe.stage_id
        )
        SELECT order_id FROM osl
        GROUP BY order_id
        HAVING MIN(stage_order) > 1 AND MAX(stage_order) > 1
    """)
    skip1_orders = [r[0] for r in cur.fetchall()]

    if not skip1_orders:
        pytest.skip("No orders skip stage 1 in generated data")

    cur.execute("SELECT order_id, missed_stages FROM v_stage_gaps")
    gap_map = {r[0]: list(r[1]) for r in cur.fetchall()}

    for oid in skip1_orders:
        assert oid in gap_map, (
            f"Order {oid} skips stage 1 but is missing from v_stage_gaps"
        )
        assert 1 in gap_map[oid], (
            f"Order {oid} skips stage 1 but missed_stages={gap_map[oid]} "
            f"does not include 1"
        )


# ====================================================================
# View 4: v_quarterly_growth
# ====================================================================

def test_quarterly_growth_exists(db):
    cur = db.cursor()
    cur.execute("SELECT * FROM v_quarterly_growth LIMIT 0")
    cols = {d[0] for d in cur.description}
    assert {"region", "year", "quarter", "growth_rate"} <= cols


def test_quarterly_growth_values(db):
    """Growth rate must divide by PREVIOUS quarter revenue, not current."""
    cur = db.cursor()
    ref = """
    WITH qr AS (
        SELECT w.region,
               EXTRACT(YEAR FROM o.order_date)::INTEGER AS year,
               EXTRACT(QUARTER FROM o.order_date)::INTEGER AS quarter,
               SUM(o.total_amount) AS total_revenue
        FROM orders o
        JOIN warehouses w ON w.warehouse_id = o.warehouse_id
        GROUP BY w.region, EXTRACT(YEAR FROM o.order_date),
                 EXTRACT(QUARTER FROM o.order_date)
    )
    SELECT region, year, quarter,
           (total_revenue - LAG(total_revenue) OVER (
               PARTITION BY region ORDER BY year, quarter
           )) / NULLIF(LAG(total_revenue) OVER (
               PARTITION BY region ORDER BY year, quarter
           ), 0) AS growth_rate
    FROM qr
    ORDER BY region, year, quarter
    """
    cur.execute(ref)
    expected = cur.fetchall()

    cur.execute(
        "SELECT region, year, quarter, growth_rate "
        "FROM v_quarterly_growth ORDER BY region, year, quarter"
    )
    actual = cur.fetchall()

    assert len(actual) == len(expected), (
        f"Row count mismatch: {len(actual)} vs {len(expected)}"
    )
    for a, e in zip(actual, expected):
        assert a[0] == e[0] and int(a[1]) == int(e[1]) and int(a[2]) == int(e[2]), (
            f"Key mismatch: ({a[0]},{a[1]},{a[2]}) vs ({e[0]},{e[1]},{e[2]})"
        )
        if e[3] is None:
            assert a[3] is None, (
                f"Expected NULL for {e[0]} {e[1]}Q{e[2]}, got {a[3]}"
            )
        else:
            assert abs(float(a[3]) - float(e[3])) < 0.0001, (
                f"Growth rate mismatch for {e[0]} {e[1]}Q{e[2]}: "
                f"{a[3]} vs {e[3]}"
            )


# ====================================================================
# View 5: v_fulfillment_velocity
# ====================================================================

def test_velocity_exists(db):
    cur = db.cursor()
    cur.execute("SELECT * FROM v_fulfillment_velocity LIMIT 0")
    cols = {d[0] for d in cur.description}
    assert {"warehouse_id", "warehouse_name", "order_count",
            "median_hours", "p90_hours", "velocity_score"} <= cols


def test_velocity_not_empty(db):
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM v_fulfillment_velocity")
    count = cur.fetchone()[0]
    assert count > 0, "v_fulfillment_velocity should have rows"


def test_velocity_only_complete_orders(db):
    """Velocity should only include orders with all 5 stages completed."""
    cur = db.cursor()
    cur.execute("SELECT SUM(order_count) FROM v_fulfillment_velocity")
    velocity_total = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM (
            SELECT oe.order_id
            FROM order_events oe
            WHERE oe.status = 'completed'
            GROUP BY oe.order_id
            HAVING COUNT(DISTINCT oe.stage_id) = 5
        ) sq
    """)
    ref_total = cur.fetchone()[0]

    assert velocity_total == ref_total, (
        f"Total order count {velocity_total} doesn't match "
        f"expected complete orders {ref_total}"
    )


def test_velocity_values(db):
    """Median, p90, and velocity_score must match reference percentile computation."""
    cur = db.cursor()
    ref = """
    WITH complete_orders AS (
        SELECT oe.order_id
        FROM order_events oe
        WHERE oe.status = 'completed'
        GROUP BY oe.order_id
        HAVING COUNT(DISTINCT oe.stage_id) = 5
    ),
    fulfillment_times AS (
        SELECT
            o.warehouse_id,
            w.warehouse_name,
            EXTRACT(EPOCH FROM (oe.completed_at - o.order_date)) / 3600.0 AS hours
        FROM complete_orders co
        JOIN orders o ON o.order_id = co.order_id
        JOIN order_events oe ON oe.order_id = co.order_id
            AND oe.stage_id = 5 AND oe.status = 'completed'
        JOIN warehouses w ON w.warehouse_id = o.warehouse_id
    )
    SELECT
        warehouse_id,
        warehouse_name,
        COUNT(*)::INTEGER AS order_count,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY hours)::NUMERIC AS median_hours,
        PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY hours)::NUMERIC AS p90_hours,
        (PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY hours) /
         NULLIF(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY hours), 0))::NUMERIC
            AS velocity_score
    FROM fulfillment_times
    GROUP BY warehouse_id, warehouse_name
    ORDER BY warehouse_id
    """
    cur.execute(ref)
    expected = cur.fetchall()

    cur.execute(
        "SELECT warehouse_id, warehouse_name, order_count, "
        "median_hours, p90_hours, velocity_score "
        "FROM v_fulfillment_velocity ORDER BY warehouse_id"
    )
    actual = cur.fetchall()

    assert len(actual) == len(expected), (
        f"Row count mismatch: {len(actual)} vs {len(expected)}"
    )
    for a, e in zip(actual, expected):
        assert a[0] == e[0], f"warehouse_id mismatch: {a[0]} vs {e[0]}"
        assert a[1] == e[1], f"warehouse_name mismatch: {a[1]} vs {e[1]}"
        assert a[2] == e[2], (
            f"order_count mismatch for wh {e[0]}: {a[2]} vs {e[2]}"
        )
        assert abs(float(a[3]) - float(e[3])) < 0.01, (
            f"median_hours mismatch for wh {e[0]}: {a[3]} vs {e[3]}"
        )
        assert abs(float(a[4]) - float(e[4])) < 0.01, (
            f"p90_hours mismatch for wh {e[0]}: {a[4]} vs {e[4]}"
        )
        assert abs(float(a[5]) - float(e[5])) < 0.001, (
            f"velocity_score mismatch for wh {e[0]}: {a[5]} vs {e[5]}"
        )


# ====================================================================
# View 6: v_health_score
# ====================================================================

def test_health_score_exists(db):
    cur = db.cursor()
    cur.execute("SELECT * FROM v_health_score LIMIT 0")
    cols = {d[0] for d in cur.description}
    assert {
        "region", "depth_score", "revenue_score",
        "gap_score", "trend_score", "velocity_score", "health_score",
    } <= cols


def test_health_score_not_empty(db):
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM v_health_score")
    count = cur.fetchone()[0]
    assert count == 3, f"Expected 3 regions in v_health_score, got {count}"


def test_health_score_values(db):
    """Health scores must match the full reference computation with 5 components."""
    cur = db.cursor()
    ref = """
    WITH RECURSIVE hierarchy AS (
        SELECT warehouse_id, region, 1 AS depth
        FROM warehouses WHERE parent_id IS NULL
        UNION ALL
        SELECT w.warehouse_id, w.region, h.depth + 1
        FROM warehouses w JOIN hierarchy h ON w.parent_id = h.warehouse_id
    ),
    depth_r AS (
        SELECT region, MAX(depth) AS max_depth FROM hierarchy GROUP BY region
    ),
    revenue_r AS (
        SELECT w.region, SUM(o.total_amount) AS total_revenue
        FROM orders o JOIN warehouses w ON w.warehouse_id = o.warehouse_id
        GROUP BY w.region
    ),
    max_rev AS (
        SELECT MAX(total_revenue) AS mr FROM revenue_r
    ),
    osl AS (
        SELECT oe.order_id, fs.stage_order
        FROM order_events oe
        JOIN fulfillment_stages fs ON fs.stage_id = oe.stage_id
    ),
    omax AS (
        SELECT order_id, MAX(stage_order) AS max_stage
        FROM osl GROUP BY order_id
    ),
    expected AS (
        SELECT om.order_id, generate_series(1, om.max_stage) AS es
        FROM omax om
    ),
    orders_with_gaps AS (
        SELECT DISTINCT e.order_id
        FROM expected e
        LEFT JOIN osl ON osl.order_id = e.order_id
            AND osl.stage_order = e.es
        WHERE osl.order_id IS NULL
    ),
    gap_counts AS (
        SELECT w.region,
               COUNT(DISTINCT owg.order_id) AS gap_orders,
               COUNT(DISTINCT o.order_id) AS total_orders
        FROM orders o
        JOIN warehouses w ON w.warehouse_id = o.warehouse_id
        LEFT JOIN orders_with_gaps owg ON owg.order_id = o.order_id
        GROUP BY w.region
    ),
    qr AS (
        SELECT w.region,
               EXTRACT(YEAR FROM o.order_date)::INTEGER AS year,
               EXTRACT(QUARTER FROM o.order_date)::INTEGER AS quarter,
               SUM(o.total_amount) AS total_revenue
        FROM orders o JOIN warehouses w ON w.warehouse_id = o.warehouse_id
        GROUP BY w.region, EXTRACT(YEAR FROM o.order_date),
                 EXTRACT(QUARTER FROM o.order_date)
    ),
    growth AS (
        SELECT region, year, quarter,
               (total_revenue - LAG(total_revenue) OVER (
                   PARTITION BY region ORDER BY year, quarter
               )) / NULLIF(LAG(total_revenue) OVER (
                   PARTITION BY region ORDER BY year, quarter
               ), 0) AS growth_rate
        FROM qr
    ),
    latest_growth AS (
        SELECT DISTINCT ON (region) region, growth_rate
        FROM growth WHERE growth_rate IS NOT NULL
        ORDER BY region, year DESC, quarter DESC
    ),
    complete_orders AS (
        SELECT oe.order_id
        FROM order_events oe
        WHERE oe.status = 'completed'
        GROUP BY oe.order_id
        HAVING COUNT(DISTINCT oe.stage_id) = 5
    ),
    fulfillment_times AS (
        SELECT
            o.warehouse_id,
            EXTRACT(EPOCH FROM (oe.completed_at - o.order_date)) / 3600.0 AS hours
        FROM complete_orders co
        JOIN orders o ON o.order_id = co.order_id
        JOIN order_events oe ON oe.order_id = co.order_id
            AND oe.stage_id = 5 AND oe.status = 'completed'
    ),
    warehouse_velocity AS (
        SELECT
            warehouse_id,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY hours) /
            NULLIF(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY hours), 0)
                AS velocity_score
        FROM fulfillment_times
        GROUP BY warehouse_id
    ),
    region_velocity AS (
        SELECT w.region, AVG(wv.velocity_score) AS avg_velocity
        FROM warehouse_velocity wv
        JOIN warehouses w ON w.warehouse_id = wv.warehouse_id
        GROUP BY w.region
    )
    SELECT
        d.region,
        (1.0 / d.max_depth) AS depth_score,
        (r.total_revenue / mr.mr) AS revenue_score,
        (1.0 - gc.gap_orders::NUMERIC / gc.total_orders) AS gap_score,
        COALESCE(lg.growth_rate, 0) AS trend_score,
        COALESCE(rv.avg_velocity, 0) AS velocity_score,
        (1.0 / d.max_depth) * 0.25 +
        (r.total_revenue / mr.mr) * 0.25 +
        (1.0 - gc.gap_orders::NUMERIC / gc.total_orders) * 0.15 +
        COALESCE(lg.growth_rate, 0) * 0.15 +
        COALESCE(rv.avg_velocity, 0) * 0.20 AS health_score
    FROM depth_r d
    JOIN revenue_r r ON r.region = d.region
    CROSS JOIN max_rev mr
    JOIN gap_counts gc ON gc.region = d.region
    LEFT JOIN latest_growth lg ON lg.region = d.region
    LEFT JOIN region_velocity rv ON rv.region = d.region
    ORDER BY d.region
    """
    cur.execute(ref)
    expected = cur.fetchall()

    cur.execute(
        "SELECT region, depth_score, revenue_score, gap_score, "
        "trend_score, velocity_score, health_score "
        "FROM v_health_score ORDER BY region"
    )
    actual = cur.fetchall()

    assert len(actual) == len(expected), (
        f"Row count mismatch: {len(actual)} vs {len(expected)}"
    )
    score_names = [
        "depth_score", "revenue_score", "gap_score",
        "trend_score", "velocity_score", "health_score",
    ]
    for a, e in zip(actual, expected):
        assert a[0] == e[0], f"Region mismatch: {a[0]} vs {e[0]}"
        for i, name in enumerate(score_names, 1):
            assert abs(float(a[i]) - float(e[i])) < 0.001, (
                f"{name} mismatch for {e[0]}: {a[i]} vs {e[i]}"
            )


def test_health_score_weights(db):
    """Verify health_score equals the weighted sum of its 5 components."""
    cur = db.cursor()
    cur.execute(
        "SELECT depth_score, revenue_score, gap_score, "
        "trend_score, velocity_score, health_score "
        "FROM v_health_score"
    )
    for row in cur.fetchall():
        d, r, g, t, v, h = [float(x) for x in row]
        expected_h = d * 0.25 + r * 0.25 + g * 0.15 + t * 0.15 + v * 0.20
        assert abs(h - expected_h) < 0.001, (
            f"health_score {h} != weighted sum {expected_h} "
            f"(d={d}, r={r}, g={g}, t={t}, v={v})"
        )
