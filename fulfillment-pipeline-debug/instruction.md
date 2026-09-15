The PostgreSQL analytics pipeline at `/app/analytics.sql` creates six views over a fulfillment-tracking database. The file contains logic bugs and two unimplemented stub views. Fix all issues so every view returns correct results when queried.

## Database

Schema: `/app/schema.sql`. Data generator: `/app/generate_data.py` (prints SQL INSERT statements to stdout, pipe to psql). Target database name: `fulfillment_analytics`. PostgreSQL is installed but not running.

## View Specifications

**v_hierarchy_revenue**: Total order revenue aggregated by hub warehouse and customer tier. Customer tier is the `customer_tier` text value extracted from each order's `metadata` JSONB column. Revenue for a hub includes orders placed at any warehouse in its recursive subtree. Columns: `hub_name` (text), `customer_tier` (text), `total_revenue` (numeric).

**v_rolling_fulfillment**: 7-day rolling average of daily delivery completion rates per region. A day's completion rate is the ratio of `status='completed'` events to total events for the delivered stage (highest `stage_order`) on that date. The window spans the current row and 6 preceding rows ordered by date. Columns: `region` (text), `calc_date` (date), `rolling_rate` (numeric).

**v_stage_gaps**: Orders that skipped expected fulfillment stages. The expected range is `stage_order` 1 through the maximum `stage_order` observed in the order's events. Any value in that range with no corresponding event is a missed stage. Columns: `order_id` (integer), `warehouse_type` (text), `missed_stages` (integer array).

**v_quarterly_growth**: Quarter-over-quarter revenue growth rate per region: `(current - previous) / previous`. Columns: `region` (text), `year` (integer), `quarter` (integer), `growth_rate` (numeric).

**v_fulfillment_velocity**: Per-warehouse fulfillment speed for orders that completed all five stages with `status='completed'`. Fulfillment time is elapsed hours from `order_date` to the `completed_at` of the delivered-stage event. Compute median and 90th-percentile fulfillment times. Velocity score = `median_hours / p90_hours`. Columns: `warehouse_id` (integer), `warehouse_name` (text), `order_count` (integer), `median_hours` (numeric), `p90_hours` (numeric), `velocity_score` (numeric).

**v_health_score**: Composite per-region health score:

    health_score = depth * 0.25 + revenue * 0.25 + gap * 0.15 + trend * 0.15 + velocity * 0.20

`depth` = 1 / max warehouse hierarchy depth in region. `revenue` = region revenue / max region revenue. `gap` = 1 - (orders with stage gaps / total orders) in region. `trend` = latest quarter growth_rate (0 if NULL). `velocity` = mean velocity_score across warehouses in region (from the v_fulfillment_velocity computation; 0 if none). Columns: `region`, `depth_score`, `revenue_score`, `gap_score`, `trend_score`, `velocity_score`, `health_score` (all numeric except region text).

## Success Criteria

All six views must exist in `fulfillment_analytics` and return correct, deterministic results.
