#!/usr/bin/env python3
"""
Fix and extend the dbt revenue reconciliation pipeline.

Fixes applied:
- Remove broken sources.yml (seeds should be referenced via ref(), not source())
- Fix stg_orders to use ref() and include currency column
- Fix stg_order_items to use ref() and add event deduplication
- Fix stg_products to use ref()
- Create stg_order_adjustments and stg_exchange_rates staging models
- Fix cents_to_dollars macro (integer division -> DOUBLE cast)
- Replace int_order_revenue with int_net_order_items (adjustment netting)
- Replace mart_revenue_summary with mart_reconciled_revenue (currency conversion,
  correct join, correct status filter)
- Create custom generic test_reconciliation macro
- Add proper schema YAML files
"""

import os

PROJECT_DIR = "/app/dbt_project"


def write_file(relative_path, content):
    path = os.path.join(PROJECT_DIR, relative_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def delete_file(relative_path):
    path = os.path.join(PROJECT_DIR, relative_path)
    if os.path.exists(path):
        os.remove(path)


# ── 1. Remove broken source configuration ──────────────────────────────
# Seeds must be referenced with ref(), not source(). source() does not
# create DAG dependencies on seeds, so dbt build tries to create views
# before seed tables exist.
delete_file("models/sources.yml")


# ── 2. Fix staging models (use ref() for seeds) ────────────────────────

write_file("models/staging/stg_orders.sql", """\
select
    order_id,
    customer_id,
    CAST(order_date AS DATE) as order_date,
    currency,
    status
from {{ ref('raw_orders') }}
""")

write_file("models/staging/stg_order_items.sql", """\
with ranked as (
    select
        event_id,
        item_id,
        order_id,
        product_id,
        quantity,
        unit_price_cents,
        CAST(event_timestamp AS TIMESTAMP) as event_timestamp,
        row_number() over (
            partition by event_id
            order by CAST(event_timestamp AS TIMESTAMP) desc
        ) as rn
    from {{ ref('raw_order_items') }}
)

select
    event_id,
    item_id,
    order_id,
    product_id,
    quantity,
    unit_price_cents
from ranked
where rn = 1
""")

write_file("models/staging/stg_products.sql", """\
select
    product_id,
    product_name,
    category
from {{ ref('raw_products') }}
""")


# ── 3. Create new staging models ───────────────────────────────────────

write_file("models/staging/stg_order_adjustments.sql", """\
select
    adjustment_id,
    order_id,
    item_id,
    adjustment_type,
    amount_cents,
    CAST(adjustment_date AS DATE) as adjustment_date
from {{ ref('raw_order_adjustments') }}
""")

write_file("models/staging/stg_exchange_rates.sql", """\
select
    currency,
    CAST(rate_to_usd AS DOUBLE) as rate_to_usd,
    CAST(effective_from AS DATE) as effective_from,
    CAST(effective_to AS DATE) as effective_to
from {{ ref('raw_exchange_rates') }}
""")


# ── 4. Fix cents_to_dollars macro ──────────────────────────────────────
# Bug: integer division (column / 100) truncates decimals in DuckDB.
# Fix: cast to DOUBLE before dividing.

write_file("macros/pricing.sql", """\
{% macro cents_to_dollars(column_name) %}
    (CAST({{ column_name }} AS DOUBLE) / 100.0)
{% endmacro %}
""")


# ── 5. Replace intermediate model with adjustment netting ──────────────
# Old int_order_revenue had no adjustment handling. New model LEFT JOINs
# items with aggregated adjustments and computes net_amount_dollars.

delete_file("models/intermediate/int_order_revenue.sql")

write_file("models/intermediate/int_net_order_items.sql", """\
with items as (
    select
        item_id,
        order_id,
        product_id,
        quantity,
        unit_price_cents,
        quantity * unit_price_cents as line_total_cents
    from {{ ref('stg_order_items') }}
),

adjustment_totals as (
    select
        order_id,
        item_id,
        sum(amount_cents) as total_adjustment_cents
    from {{ ref('stg_order_adjustments') }}
    group by order_id, item_id
)

select
    i.item_id,
    i.order_id,
    i.product_id,
    i.quantity,
    i.unit_price_cents,
    i.line_total_cents,
    coalesce(a.total_adjustment_cents, 0) as adjustment_cents,
    i.line_total_cents + coalesce(a.total_adjustment_cents, 0) as net_amount_cents,
    {{ cents_to_dollars('i.line_total_cents + coalesce(a.total_adjustment_cents, 0)') }} as net_amount_dollars
from items i
left join adjustment_totals a
    on i.order_id = a.order_id
    and i.item_id = a.item_id
""")


# ── 6. Replace mart model ──────────────────────────────────────────────
# Old mart_revenue_summary had: wrong join (item_id vs order_id),
# wrong status filter ('complete' vs 'completed'), no currency conversion.
# New mart_reconciled_revenue joins with exchange rates for USD conversion.

delete_file("models/marts/mart_revenue_summary.sql")

write_file("models/marts/mart_reconciled_revenue.sql", """\
select
    o.order_date,
    p.category,
    round(sum(r.net_amount_dollars * er.rate_to_usd), 2) as total_revenue_usd,
    count(distinct o.order_id) as order_count
from {{ ref('stg_orders') }} o
inner join {{ ref('int_net_order_items') }} r
    on o.order_id = r.order_id
inner join {{ ref('stg_products') }} p
    on r.product_id = p.product_id
inner join {{ ref('stg_exchange_rates') }} er
    on o.currency = er.currency
    and o.order_date >= er.effective_from
    and o.order_date <= er.effective_to
where o.status = 'completed'
group by 1, 2
""")


# ── 7. Custom generic test: reconciliation ─────────────────────────────
# Returns rows only when mart total diverges from direct calculation.

write_file("macros/test_reconciliation.sql", """\
{% test reconciliation(model, column_name) %}

with mart_total as (
    select round(sum({{ column_name }}), 2) as total
    from {{ model }}
),

direct_calc as (
    select round(sum(
        noi.net_amount_dollars * er.rate_to_usd
    ), 2) as total
    from {{ ref('int_net_order_items') }} noi
    inner join {{ ref('stg_orders') }} o
        on noi.order_id = o.order_id
    inner join {{ ref('stg_exchange_rates') }} er
        on o.currency = er.currency
        and o.order_date >= er.effective_from
        and o.order_date <= er.effective_to
    where o.status = 'completed'
)

select
    mart_total.total as mart_revenue,
    direct_calc.total as expected_revenue
from mart_total
cross join direct_calc
where abs(mart_total.total - direct_calc.total) > 0.01

{% endtest %}
""")


# ── 8. Schema YAML files ──────────────────────────────────────────────

write_file("models/staging/_staging.yml", """\
version: 2

models:
  - name: stg_orders
    description: "Staged orders with type-cast columns and currency"
    columns:
      - name: order_id
        tests:
          - unique
          - not_null
      - name: status
        tests:
          - not_null
      - name: currency
        tests:
          - not_null

  - name: stg_order_items
    description: "Staged order items, deduplicated by event_id"
    columns:
      - name: item_id
        tests:
          - unique
          - not_null
      - name: order_id
        tests:
          - not_null

  - name: stg_products
    description: "Staged products dimension"
    columns:
      - name: product_id
        tests:
          - unique
          - not_null

  - name: stg_order_adjustments
    description: "Staged order adjustments (refunds, price corrections)"
    columns:
      - name: adjustment_id
        tests:
          - unique
          - not_null

  - name: stg_exchange_rates
    description: "Staged exchange rates with effective date ranges"
    columns:
      - name: currency
        tests:
          - not_null
      - name: rate_to_usd
        tests:
          - not_null
""")

write_file("models/intermediate/_intermediate.yml", """\
version: 2

models:
  - name: int_net_order_items
    description: "Order line items with net amounts after adjustment netting"
    columns:
      - name: item_id
        tests:
          - unique
          - not_null
      - name: net_amount_dollars
        tests:
          - not_null
""")

write_file("models/marts/_marts.yml", """\
version: 2

models:
  - name: mart_reconciled_revenue
    description: "Daily revenue by product category in USD, net of adjustments"
    columns:
      - name: order_date
        tests:
          - not_null
      - name: category
        tests:
          - not_null
      - name: total_revenue_usd
        tests:
          - not_null
          - reconciliation
      - name: order_count
        tests:
          - not_null
""")


print("Pipeline fixed and extended successfully.")
print("All models, macros, schema tests, and custom generic test are in place.")
print("Run 'cd /app/dbt_project && dbt build' to verify.")
