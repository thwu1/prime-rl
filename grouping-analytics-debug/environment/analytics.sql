
-----------------------------------------------------------------------
-- Function: margin_category
-- Classifies profit margin into tiers based on margin percentage.
-- Parameters: p_cost (cost value), p_revenue (revenue value)
-- Returns a tier label string.
-----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION margin_category(p_cost NUMERIC, p_revenue NUMERIC)
RETURNS TEXT LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    margin_pct NUMERIC;
BEGIN
    IF p_revenue = 0 THEN RETURN 'undefined'; END IF;
    margin_pct := (p_revenue - p_cost) * 100.0 / p_cost;
    IF margin_pct < 20 THEN RETURN 'low';
    ELSIF margin_pct < 40 THEN RETURN 'standard';
    ELSIF margin_pct <= 60 THEN RETURN 'high';
    ELSE RETURN 'premium';
    END IF;
END;
$$;


-----------------------------------------------------------------------
-- View 1: v_sales_enriched
-- Enriches sales rows with margin tier, running revenue total
-- within each region ordered by date, and rank by amount.
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_sales_enriched AS
SELECT s.*,
    margin_category(amount, cost) AS margin_tier,
    SUM(amount) OVER (
        PARTITION BY region
        ORDER BY sale_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    ) AS running_total,
    RANK() OVER (
        PARTITION BY region
        ORDER BY amount DESC
    ) AS amount_rank
FROM sales s;


-----------------------------------------------------------------------
-- View 2: v_cube_analysis
-- Multi-dimensional summary using CUBE on region and category.
-- Produces detail rows, subtotals, and a grand total with labels.
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_cube_analysis AS
SELECT region, category,
    SUM(amount) AS total_revenue,
    SUM(cost) AS total_cost,
    COUNT(*) AS num_txns,
    GROUPING(region) AS g_region,
    GROUPING(category) AS g_category,
    CASE GROUPING(region, category)
        WHEN 0 THEN 'detail'
        WHEN 1 THEN 'by_category'
        WHEN 2 THEN 'by_region'
        WHEN 3 THEN 'grand_total'
    END AS level_label
FROM sales
GROUP BY ROLLUP(region, category);


-----------------------------------------------------------------------
-- View 3: v_channel_metrics
-- Revenue breakdown by region with channel-filtered aggregates,
-- distinct category count, and high-quantity subtotals.
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_channel_metrics AS
SELECT region,
    SUM(amount) AS total_revenue,
    SUM(amount) FILTER (WHERE channel = 'Online') AS online_revenue,
    SUM(amount) FILTER (WHERE channel = 'retail') AS retail_revenue,
    COUNT(category) AS num_categories,
    SUM(amount) FILTER (WHERE quantity >= 5) AS high_qty_revenue,
    ROUND(SUM(amount - cost) * 100.0 / NULLIF(SUM(amount), 0), 2) AS profit_margin_pct
FROM sales
GROUP BY ROLLUP(region)
ORDER BY GROUPING(region), region;


-----------------------------------------------------------------------
-- View 4: v_threshold_regions
-- Regions exceeding the equal-share revenue threshold.
-- Uses HAVING with a subquery to filter groups.
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_threshold_regions AS
SELECT region,
    SUM(amount) AS total_revenue,
    ROUND(SUM(amount) * 100.0 / (SELECT SUM(cost) FROM sales), 2) AS pct_of_total
FROM sales
GROUP BY ROLLUP(region)
HAVING SUM(amount) >= (SELECT AVG(amount) FROM sales)
ORDER BY GROUPING(region), region;


-----------------------------------------------------------------------
-- View 5: v_quarterly_growth  [STUB — implement from scratch]
-- Quarter-over-quarter revenue analysis with growth rates.
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_quarterly_growth AS
SELECT NULL::INT AS quarter_num, NULL::TEXT AS region,
    NULL::NUMERIC AS total_revenue, NULL::NUMERIC AS total_cost,
    NULL::NUMERIC AS profit_margin_pct, NULL::INT AS g_region,
    NULL::INT AS g_quarter,
    NULL::NUMERIC AS growth_rate_pct
WHERE FALSE;


-----------------------------------------------------------------------
-- View 6: v_ranked_tiers
-- Top performers within each margin tier, ranked by amount.
-- Depends on v_sales_enriched for margin classification.
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_ranked_tiers AS
WITH enriched AS (
    SELECT region, category, amount, margin_tier
    FROM v_sales_enriched
),
tier_ranked AS (
    SELECT region, category, amount, margin_tier,
        DENSE_RANK() OVER (
            PARTITION BY region
            ORDER BY amount DESC
        ) AS tier_rank
    FROM enriched
)
SELECT * FROM tier_ranked
WHERE tier_rank > 3
ORDER BY margin_tier, tier_rank, region;
