#!/usr/bin/env python3

"""Compute all four analytics outputs for the ecommerce pipeline task."""

import duckdb
import os

DB_PATH = '/app/ecommerce.duckdb'
OUTPUT_DIR = '/app/output'
os.makedirs(OUTPUT_DIR, exist_ok=True)

conn = duckdb.connect(DB_PATH)

# Verify tables exist
tables = [r[0] for r in conn.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name"
).fetchall()]
print(f"Tables in database: {tables}")
assert 'refunds' in tables, f"refunds table missing! Found: {tables}"

# ---------------------------------------------------------------------------
# 1. Position-Based Channel Attribution (Net Revenue)
# ---------------------------------------------------------------------------
attribution_sql = """
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

result = conn.execute(attribution_sql).fetchdf()
result.to_csv(os.path.join(OUTPUT_DIR, 'channel_attribution.csv'), index=False)
print(f"channel_attribution.csv: {len(result)} rows")

# ---------------------------------------------------------------------------
# 2. Monthly Cohort Retention
# ---------------------------------------------------------------------------
retention_sql = """
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

result = conn.execute(retention_sql).fetchdf()
result.to_csv(os.path.join(OUTPUT_DIR, 'cohort_retention.csv'), index=False)
print(f"cohort_retention.csv: {len(result)} rows")

# ---------------------------------------------------------------------------
# 3. RFM Customer Segmentation (Net Revenue)
# ---------------------------------------------------------------------------
rfm_sql = """
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

result = conn.execute(rfm_sql).fetchdf()
result.to_csv(os.path.join(OUTPUT_DIR, 'rfm_segments.csv'), index=False)
print(f"rfm_segments.csv: {len(result)} rows")

# ---------------------------------------------------------------------------
# 4. Category Cross-Sell Lift Analysis
# ---------------------------------------------------------------------------
cross_sell_sql = """
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

result = conn.execute(cross_sell_sql).fetchdf()
result.to_csv(os.path.join(OUTPUT_DIR, 'cross_sell.csv'), index=False)
print(f"cross_sell.csv: {len(result)} rows")

conn.close()
print("All outputs generated successfully.")
