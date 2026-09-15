# Revenue Reconciliation Pipeline Requirements

Build a dbt pipeline that produces a `mart_reconciled_revenue` model providing daily revenue aggregated by product category, with all amounts converted to USD.

## Data Characteristics

- **raw_order_items** contains duplicate event records — the same `event_id` may appear multiple times with different `event_timestamp` values due to upstream event replay. Only the most recent record per `event_id` (by `event_timestamp`) should be retained.
- **raw_order_adjustments** contains post-sale adjustments (refunds, price corrections) tied to specific order items. The `amount_cents` field is pre-signed: negative values reduce revenue.
- **raw_exchange_rates** provides currency-to-USD conversion rates with effective date ranges. For a given order, use the rate where the order's `order_date` falls within `effective_from` and `effective_to` (inclusive on both ends).
- All monetary amounts in source tables are denominated in **cents** and must be converted to **dollars** (divide by 100).
- Only orders with `status = 'completed'` contribute to revenue.

## Revenue Calculation

Net revenue per line item (in the order's local currency):

    net_local = (quantity * unit_price_cents + sum_of_adjustment_cents) / 100

Items without adjustments have a net equal to their line total. Convert to USD by multiplying by the applicable `rate_to_usd`.

## Required Output: `mart_reconciled_revenue`

| Column | Type | Description |
|--------|------|-------------|
| `order_date` | DATE | Date of the orders |
| `category` | VARCHAR | Product category from the products table |
| `total_revenue_usd` | DOUBLE | Sum of net line item revenues converted to USD, rounded to 2 decimal places |
| `order_count` | INTEGER | Count of distinct completed orders |

## Additional Requirements

- Create a **custom generic dbt test** named `test_reconciliation` that validates the mart's total revenue matches a direct calculation from the underlying intermediate/staging models. The test must be reusable (defined as a macro, not a singular test) and applied to the mart via schema YAML.
- All models should have appropriate schema tests (not_null, unique where applicable, accepted_values, etc.) defined in YAML files.
- Follow dbt best practices: staging models for source abstraction, intermediate models for business logic, mart models for final aggregation.
