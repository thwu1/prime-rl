A DuckDB database at `/app/ecommerce.duckdb` contains operational data for an e-commerce platform. The schema is undocumented — explore it to understand the data model, table relationships, and which financial records reflect post-sale adjustments versus pre-sale discounts already factored into transaction totals.

All revenue figures must reflect the real economic value retained by the company from each transaction. Produce four CSV files in `/app/output/`.

## 1. `/app/output/channel_attribution.csv`

For each completed order, gather all browsing sessions by the same user that began within 30 days before the order timestamp (inclusive of both endpoints). These marketing touchpoints should be ordered chronologically, with session identifier as a tiebreaker for simultaneous sessions.

Distribute order revenue across touchpoint channels:
- Single touchpoint: 100%
- Two touchpoints: 50% / 50%
- Three or more: 40% to first, 40% to last, 20% divided equally among middle touchpoints

Columns: `channel`, `attributed_revenue` (2 decimal places), `touchpoint_count`. Sort descending by `attributed_revenue`.

## 2. `/app/output/cohort_retention.csv`

Group users by signup month. For each cohort, calculate the percentage of members who placed at least one completed order in months 0–5 relative to the cohort's start month (month 0 = signup calendar month; month N = exactly N calendar months later).

Columns: `cohort_month` (YYYY-MM), `cohort_size`, `month_0` through `month_5` (percentages, 1 decimal place). Sort ascending by `cohort_month`.

## 3. `/app/output/rfm_segments.csv`

Evaluate every customer with at least one completed order along three value dimensions, measured against reference timestamp 2024-01-01 00:00:00:

- Days since most recent completed order
- Number of completed orders
- Total revenue from completed orders

Divide customers into five equal-sized buckets per dimension, scored 1 (worst) to 5 (best). Fewer days since last purchase, more orders, and higher revenue are better. Break ties at bucket boundaries by user ID ascending.

Assign each customer to the first matching segment:
1. **Champions** — all scores ≥ 4
2. **Loyal** — all scores ≥ 3
3. **At Risk** — recency ≤ 2 and frequency ≥ 3
4. **Lost** — recency ≤ 2 and frequency ≤ 2
5. **Other** — everyone else

Columns: `segment`, `customer_count`, `avg_monetary` (2 decimal places). Sort descending by `customer_count`.

## 4. `/app/output/cross_sell.csv`

Among completed orders with positive revenue, find every unordered pair of product categories that co-occur in at least one order. Quantify how much more (or less) frequently each pair co-occurs compared to what statistical independence would predict.

Columns: `category_a`, `category_b` (alphabetical within pair), `co_occurrence_count`, `lift` (4 decimal places). Sort descending by `lift`, then ascending by `category_a`.