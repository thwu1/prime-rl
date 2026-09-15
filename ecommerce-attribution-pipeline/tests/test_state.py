
"""Tests for ecommerce analytics pipeline outputs."""

import os
import duckdb
import pandas as pd
import numpy as np
import pytest

DB_PATH = '/app/ecommerce.duckdb'
OUTPUT_DIR = '/app/output'


@pytest.fixture(scope='module')
def conn():
    c = duckdb.connect(DB_PATH)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# 1. Channel Attribution (Net Revenue)
# ---------------------------------------------------------------------------

ATTRIBUTION_SQL = """
WITH order_refunds AS (
    SELECT order_id, SUM(refund_amount) AS total_refund
    FROM refunds
    GROUP BY order_id
),
completed_orders AS (
    SELECT o.order_id, o.user_id, o.session_id, o.created_at,
           o.total_amount - COALESCE(r.total_refund, 0) AS net_amount
    FROM orders o
    LEFT JOIN order_refunds r ON o.order_id = r.order_id
    WHERE o.status = 'completed'
),
touchpoints AS (
    SELECT
        co.order_id,
        co.net_amount,
        s.session_id,
        s.channel,
        s.started_at,
        ROW_NUMBER() OVER (
            PARTITION BY co.order_id
            ORDER BY s.started_at ASC, s.session_id ASC
        ) AS pos,
        COUNT(*) OVER (PARTITION BY co.order_id) AS total_touches
    FROM completed_orders co
    JOIN sessions s ON s.user_id = co.user_id
    WHERE s.started_at <= co.created_at
      AND s.started_at >= co.created_at - INTERVAL '30 days'
),
attributed AS (
    SELECT
        channel,
        CASE
            WHEN total_touches = 1 THEN net_amount * 1.0
            WHEN total_touches = 2 AND pos = 1 THEN net_amount * 0.5
            WHEN total_touches = 2 AND pos = 2 THEN net_amount * 0.5
            WHEN pos = 1 THEN net_amount * 0.4
            WHEN pos = total_touches THEN net_amount * 0.4
            ELSE net_amount * 0.2 / (total_touches - 2)
        END AS attr_revenue
    FROM touchpoints
)
SELECT
    channel,
    ROUND(SUM(attr_revenue), 2) AS attributed_revenue,
    COUNT(*) AS touchpoint_count
FROM attributed
GROUP BY channel
ORDER BY attributed_revenue DESC
"""


def test_channel_attribution_exists():
    path = os.path.join(OUTPUT_DIR, 'channel_attribution.csv')
    assert os.path.exists(path), "channel_attribution.csv not found in /app/output/"


def test_channel_attribution_columns():
    actual = pd.read_csv(os.path.join(OUTPUT_DIR, 'channel_attribution.csv'))
    actual.columns = [c.strip().lower() for c in actual.columns]
    required = {'channel', 'attributed_revenue', 'touchpoint_count'}
    assert required.issubset(set(actual.columns)), \
        f"Missing columns. Expected {required}, got {set(actual.columns)}"


def test_channel_attribution_values(conn):
    expected = conn.execute(ATTRIBUTION_SQL).fetchdf()
    actual = pd.read_csv(os.path.join(OUTPUT_DIR, 'channel_attribution.csv'))
    actual.columns = [c.strip().lower() for c in actual.columns]

    assert len(actual) == len(expected), \
        f"Row count mismatch: expected {len(expected)}, got {len(actual)}"

    exp_sorted = expected.sort_values('channel').reset_index(drop=True)
    act_sorted = actual.sort_values('channel').reset_index(drop=True)

    for i in range(len(exp_sorted)):
        ch = exp_sorted.iloc[i]['channel']
        act_row = act_sorted[act_sorted['channel'] == ch]
        assert len(act_row) == 1, f"Channel '{ch}' not found in output"

        exp_rev = float(exp_sorted.iloc[i]['attributed_revenue'])
        act_rev = float(act_row['attributed_revenue'].values[0])
        assert abs(exp_rev - act_rev) < 0.05, \
            f"Revenue mismatch for '{ch}': expected {exp_rev}, got {act_rev}"

        exp_tc = int(exp_sorted.iloc[i]['touchpoint_count'])
        act_tc = int(act_row['touchpoint_count'].values[0])
        assert exp_tc == act_tc, \
            f"Touchpoint count mismatch for '{ch}': expected {exp_tc}, got {act_tc}"


# ---------------------------------------------------------------------------
# 2. Cohort Retention
# ---------------------------------------------------------------------------

RETENTION_SQL = """
WITH user_cohorts AS (
    SELECT
        user_id,
        DATE_TRUNC('month', signup_date) AS cohort_month
    FROM users
),
user_orders AS (
    SELECT DISTINCT
        o.user_id,
        DATE_TRUNC('month', CAST(o.created_at AS DATE)) AS order_month
    FROM orders o
    WHERE o.status = 'completed'
),
cohort_activity AS (
    SELECT
        uc.cohort_month,
        uc.user_id,
        DATEDIFF('month', uc.cohort_month, uo.order_month) AS months_since
    FROM user_cohorts uc
    JOIN user_orders uo ON uc.user_id = uo.user_id
),
cohort_sizes AS (
    SELECT cohort_month, COUNT(DISTINCT user_id) AS cohort_size
    FROM user_cohorts
    GROUP BY cohort_month
)
SELECT
    STRFTIME(cs.cohort_month, '%Y-%m') AS cohort_month,
    cs.cohort_size,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN ca.months_since = 0 THEN ca.user_id END) / cs.cohort_size, 1) AS month_0,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN ca.months_since = 1 THEN ca.user_id END) / cs.cohort_size, 1) AS month_1,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN ca.months_since = 2 THEN ca.user_id END) / cs.cohort_size, 1) AS month_2,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN ca.months_since = 3 THEN ca.user_id END) / cs.cohort_size, 1) AS month_3,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN ca.months_since = 4 THEN ca.user_id END) / cs.cohort_size, 1) AS month_4,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN ca.months_since = 5 THEN ca.user_id END) / cs.cohort_size, 1) AS month_5
FROM cohort_sizes cs
LEFT JOIN cohort_activity ca ON cs.cohort_month = ca.cohort_month
GROUP BY cs.cohort_month, cs.cohort_size
ORDER BY cs.cohort_month
"""


def test_cohort_retention_exists():
    path = os.path.join(OUTPUT_DIR, 'cohort_retention.csv')
    assert os.path.exists(path), "cohort_retention.csv not found in /app/output/"


def test_cohort_retention_columns():
    actual = pd.read_csv(os.path.join(OUTPUT_DIR, 'cohort_retention.csv'))
    actual.columns = [c.strip().lower() for c in actual.columns]
    required = {'cohort_month', 'cohort_size', 'month_0', 'month_1',
                'month_2', 'month_3', 'month_4', 'month_5'}
    assert required.issubset(set(actual.columns)), \
        f"Missing columns. Expected {required}, got {set(actual.columns)}"


def test_cohort_retention_values(conn):
    expected = conn.execute(RETENTION_SQL).fetchdf()
    actual = pd.read_csv(os.path.join(OUTPUT_DIR, 'cohort_retention.csv'))
    actual.columns = [c.strip().lower() for c in actual.columns]

    actual['cohort_month'] = actual['cohort_month'].astype(str).str.strip()
    expected['cohort_month'] = expected['cohort_month'].astype(str).str.strip()

    assert len(actual) == len(expected), \
        f"Row count mismatch: expected {len(expected)}, got {len(actual)}"

    for _, exp_row in expected.iterrows():
        cm = exp_row['cohort_month']
        act_row = actual[actual['cohort_month'] == cm]
        assert len(act_row) == 1, f"Cohort '{cm}' not found in output"

        act_size = int(act_row['cohort_size'].values[0])
        exp_size = int(exp_row['cohort_size'])
        assert act_size == exp_size, \
            f"Cohort size mismatch for '{cm}': expected {exp_size}, got {act_size}"

        for m in range(6):
            col = f'month_{m}'
            exp_val = float(exp_row[col])
            act_val = float(act_row[col].values[0])
            assert abs(exp_val - act_val) < 0.15, \
                f"Retention mismatch for '{cm}' {col}: expected {exp_val}, got {act_val}"


# ---------------------------------------------------------------------------
# 3. RFM Segmentation (Net Revenue)
# ---------------------------------------------------------------------------

RFM_SQL = """
WITH order_refunds AS (
    SELECT order_id, SUM(refund_amount) AS total_refund
    FROM refunds
    GROUP BY order_id
),
order_net AS (
    SELECT o.order_id, o.user_id, o.created_at,
           o.total_amount - COALESCE(r.total_refund, 0) AS net_amount
    FROM orders o
    LEFT JOIN order_refunds r ON o.order_id = r.order_id
    WHERE o.status = 'completed'
),
customer_metrics AS (
    SELECT
        user_id,
        DATEDIFF('day', MAX(created_at), TIMESTAMP '2024-01-01') AS recency,
        COUNT(*) AS frequency,
        ROUND(CAST(SUM(net_amount) AS DOUBLE), 2) AS monetary
    FROM order_net
    GROUP BY user_id
),
rfm_scores AS (
    SELECT
        user_id,
        recency, frequency, monetary,
        NTILE(5) OVER (ORDER BY recency DESC, user_id ASC) AS r_score,
        NTILE(5) OVER (ORDER BY frequency ASC, user_id ASC) AS f_score,
        NTILE(5) OVER (ORDER BY monetary ASC, user_id ASC) AS m_score
    FROM customer_metrics
),
segments AS (
    SELECT
        user_id,
        monetary,
        CASE
            WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'Champions'
            WHEN r_score >= 3 AND f_score >= 3 AND m_score >= 3 THEN 'Loyal'
            WHEN r_score <= 2 AND f_score >= 3 THEN 'At Risk'
            WHEN r_score <= 2 AND f_score <= 2 THEN 'Lost'
            ELSE 'Other'
        END AS segment
    FROM rfm_scores
)
SELECT
    segment,
    COUNT(*) AS customer_count,
    ROUND(AVG(monetary), 2) AS avg_monetary
FROM segments
GROUP BY segment
ORDER BY customer_count DESC
"""


def test_rfm_segments_exists():
    path = os.path.join(OUTPUT_DIR, 'rfm_segments.csv')
    assert os.path.exists(path), "rfm_segments.csv not found in /app/output/"


def test_rfm_segments_columns():
    actual = pd.read_csv(os.path.join(OUTPUT_DIR, 'rfm_segments.csv'))
    actual.columns = [c.strip().lower() for c in actual.columns]
    required = {'segment', 'customer_count', 'avg_monetary'}
    assert required.issubset(set(actual.columns)), \
        f"Missing columns. Expected {required}, got {set(actual.columns)}"


def test_rfm_segments_values(conn):
    expected = conn.execute(RFM_SQL).fetchdf()
    actual = pd.read_csv(os.path.join(OUTPUT_DIR, 'rfm_segments.csv'))
    actual.columns = [c.strip().lower() for c in actual.columns]

    assert len(actual) == len(expected), \
        f"Row count mismatch: expected {len(expected)}, got {len(actual)}"

    for _, exp_row in expected.iterrows():
        seg = exp_row['segment']
        act_row = actual[actual['segment'] == seg]
        assert len(act_row) == 1, f"Segment '{seg}' not found in output"

        exp_count = int(exp_row['customer_count'])
        act_count = int(act_row['customer_count'].values[0])
        assert exp_count == act_count, \
            f"Count mismatch for '{seg}': expected {exp_count}, got {act_count}"

        exp_avg = float(exp_row['avg_monetary'])
        act_avg = float(act_row['avg_monetary'].values[0])
        assert abs(exp_avg - act_avg) < 1.0, \
            f"Avg monetary mismatch for '{seg}': expected {exp_avg}, got {act_avg}"


# ---------------------------------------------------------------------------
# 4. Category Cross-Sell Lift
# ---------------------------------------------------------------------------

CROSS_SELL_SQL = """
WITH order_refunds AS (
    SELECT order_id, SUM(refund_amount) AS total_refund
    FROM refunds
    GROUP BY order_id
),
qualifying_orders AS (
    SELECT o.order_id
    FROM orders o
    LEFT JOIN order_refunds r ON o.order_id = r.order_id
    WHERE o.status = 'completed'
      AND o.total_amount - COALESCE(r.total_refund, 0) > 0
),
order_categories AS (
    SELECT DISTINCT qo.order_id, p.category
    FROM qualifying_orders qo
    JOIN order_items oi ON qo.order_id = oi.order_id
    JOIN products p ON oi.product_id = p.product_id
),
total_orders AS (
    SELECT CAST(COUNT(DISTINCT order_id) AS DOUBLE) AS n
    FROM qualifying_orders
),
category_counts AS (
    SELECT category, CAST(COUNT(DISTINCT order_id) AS DOUBLE) AS cat_count
    FROM order_categories
    GROUP BY category
),
pairs AS (
    SELECT
        a.category AS category_a,
        b.category AS category_b,
        COUNT(DISTINCT a.order_id) AS co_occurrence_count
    FROM order_categories a
    JOIN order_categories b ON a.order_id = b.order_id AND a.category < b.category
    GROUP BY a.category, b.category
)
SELECT
    p.category_a,
    p.category_b,
    p.co_occurrence_count,
    ROUND(
        (CAST(p.co_occurrence_count AS DOUBLE) * t.n) / (ca.cat_count * cb.cat_count),
        4
    ) AS lift
FROM pairs p
CROSS JOIN total_orders t
JOIN category_counts ca ON p.category_a = ca.category
JOIN category_counts cb ON p.category_b = cb.category
ORDER BY lift DESC, category_a ASC
"""


def test_cross_sell_exists():
    path = os.path.join(OUTPUT_DIR, 'cross_sell.csv')
    assert os.path.exists(path), "cross_sell.csv not found in /app/output/"


def test_cross_sell_columns():
    actual = pd.read_csv(os.path.join(OUTPUT_DIR, 'cross_sell.csv'))
    actual.columns = [c.strip().lower() for c in actual.columns]
    required = {'category_a', 'category_b', 'co_occurrence_count', 'lift'}
    assert required.issubset(set(actual.columns)), \
        f"Missing columns. Expected {required}, got {set(actual.columns)}"


def test_cross_sell_values(conn):
    expected = conn.execute(CROSS_SELL_SQL).fetchdf()
    actual = pd.read_csv(os.path.join(OUTPUT_DIR, 'cross_sell.csv'))
    actual.columns = [c.strip().lower() for c in actual.columns]

    assert len(actual) == len(expected), \
        f"Row count mismatch: expected {len(expected)}, got {len(actual)}"

    for _, exp_row in expected.iterrows():
        ca = exp_row['category_a']
        cb = exp_row['category_b']
        act_row = actual[
            (actual['category_a'] == ca) & (actual['category_b'] == cb)
        ]
        assert len(act_row) == 1, \
            f"Pair ('{ca}', '{cb}') not found in output"

        exp_count = int(exp_row['co_occurrence_count'])
        act_count = int(act_row['co_occurrence_count'].values[0])
        assert exp_count == act_count, \
            f"Co-occurrence mismatch for ('{ca}', '{cb}'): expected {exp_count}, got {act_count}"

        exp_lift = float(exp_row['lift'])
        act_lift = float(act_row['lift'].values[0])
        assert abs(exp_lift - act_lift) < 0.001, \
            f"Lift mismatch for ('{ca}', '{cb}'): expected {exp_lift}, got {act_lift}"
