#!/usr/bin/env python3
"""
Programmatically fix all bugs and create missing components in the
dbt e-commerce pipeline project.

Bugs 1-7: Configuration, macro, DAG, incremental, variable, and test fixes
Bug 8: Create missing customer_lifetime_tiers model (referenced in _marts.yml)
Bug 9: Create missing within_range custom generic test macro (referenced in _marts.yml)
"""

import os

PROJECT = '/app/dbt_project'


def read(path):
    with open(os.path.join(PROJECT, path)) as f:
        return f.read()


def write(path, content):
    full = os.path.join(PROJECT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w') as f:
        f.write(content)


def fix_bug1_profile_name():
    """Fix: rename profile key from 'ecommerce_analytics' to 'ecommerce_pipeline'."""
    content = read('profiles.yml')
    content = content.replace('ecommerce_analytics:', 'ecommerce_pipeline:')
    write('profiles.yml', content)


def fix_bug2_source_schema():
    """Fix: change source schema from 'raw' to 'main'."""
    content = read('models/staging/_src.yml')
    content = content.replace('schema: raw', 'schema: main')
    write('models/staging/_src.yml', content)


def fix_bug3_macro_variable():
    """Fix: replace undefined '{{ col }}' with '{{ column_name }}' in macro."""
    content = read('macros/cents_to_dollars.sql')
    content = content.replace('{{ col }}', '{{ column_name }}')
    write('macros/cents_to_dollars.sql', content)


def fix_bug4_circular_dependency():
    """Fix: break the cycle by removing cross-references in intermediate models.
    Each intermediate model should only reference staging models, not each other."""
    # int_customer_order_history: remove dependency on int_payment_type_amounts
    write('models/intermediate/int_customer_order_history.sql', """\
with customers as (
    select * from {{ ref('stg_customers') }}
),

orders as (
    select * from {{ ref('stg_orders') }}
)

select
    customers.customer_id,
    customers.first_name,
    customers.last_name,
    min(orders.order_date) as first_order_date,
    max(orders.order_date) as most_recent_order_date,
    count(distinct orders.order_id) as number_of_orders
from customers
left join orders on customers.customer_id = orders.customer_id
group by 1, 2, 3
""")

    # int_payment_type_amounts: remove dependency on int_customer_order_history
    write('models/intermediate/int_payment_type_amounts.sql', """\
with payments as (
    select * from {{ ref('stg_payments') }}
),

orders as (
    select * from {{ ref('stg_orders') }}
)

select
    orders.order_id,
    orders.customer_id,
    sum(case when payments.payment_method = 'credit_card' then payments.amount else 0 end) as credit_card_amount,
    sum(case when payments.payment_method = 'bank_transfer' then payments.amount else 0 end) as bank_transfer_amount,
    sum(case when payments.payment_method = 'coupon' then payments.amount else 0 end) as coupon_amount,
    sum(payments.amount) as total_amount
from payments
left join orders on payments.order_id = orders.order_id
group by 1, 2
""")


def fix_bug5_incremental_model():
    """Fix: correct unique_key from 'date' to 'order_date', and fix
    is_incremental filter from '_loaded_at' to 'order_date'."""
    content = read('models/marts/revenue_daily.sql')
    content = content.replace("unique_key='date'", "unique_key='order_date'")
    content = content.replace(
        "orders._loaded_at > (select max(_loaded_at) from {{ this }})",
        "orders.order_date > (select max(order_date) from {{ this }})",
    )
    write('models/marts/revenue_daily.sql', content)


def fix_bug6_var_name():
    """Fix: change var('pay_methods') to var('payment_methods')."""
    content = read('models/marts/fct_orders.sql')
    content = content.replace("var('pay_methods')", "var('payment_methods')")
    write('models/marts/fct_orders.sql', content)


def fix_bug7_test_logic():
    """Fix: invert the is_positive test condition from > 0 to <= 0.
    dbt tests should return FAILING rows; > 0 returns valid rows."""
    content = read('macros/test_is_positive.sql')
    content = content.replace('> 0', '<= 0')
    write('macros/test_is_positive.sql', content)


def create_bug8_customer_lifetime_tiers():
    """Create the missing customer_lifetime_tiers model.
    Uses dim_customers for lifetime_value and the tier_thresholds project
    variable (a dict with platinum/gold/silver keys) for tier assignment.
    Adds ntile(4) window function for value_quartile ranking."""
    write('models/marts/customer_lifetime_tiers.sql', """\
with customers as (
    select * from {{ ref('dim_customers') }}
)

select
    customer_id,
    first_name,
    last_name,
    lifetime_value,
    case
        when lifetime_value >= {{ var('tier_thresholds')['platinum'] }} then 'platinum'
        when lifetime_value >= {{ var('tier_thresholds')['gold'] }} then 'gold'
        when lifetime_value >= {{ var('tier_thresholds')['silver'] }} then 'silver'
        else 'bronze'
    end as tier,
    ntile(4) over (order by lifetime_value desc) as value_quartile
from customers
""")


def create_bug9_within_range_test():
    """Create the missing within_range custom generic test macro.
    Per dbt's test contract, returns FAILING rows — rows where the
    column value falls outside the [min_value, max_value] range."""
    write('macros/test_within_range.sql', """\
{% test within_range(model, column_name, min_value, max_value) %}

select *
from {{ model }}
where {{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }}

{% endtest %}
""")


if __name__ == '__main__':
    fix_bug1_profile_name()
    fix_bug2_source_schema()
    fix_bug3_macro_variable()
    fix_bug4_circular_dependency()
    fix_bug5_incremental_model()
    fix_bug6_var_name()
    fix_bug7_test_logic()
    create_bug8_customer_lifetime_tiers()
    create_bug9_within_range_test()
    print("All bugs fixed and missing components created.")
