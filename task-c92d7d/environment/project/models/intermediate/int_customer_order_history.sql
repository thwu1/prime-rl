with customers as (
    select * from {{ ref('stg_customers') }}
),

orders as (
    select * from {{ ref('stg_orders') }}
),

payment_totals as (
    select * from {{ ref('int_payment_type_amounts') }}
)

select
    customers.customer_id,
    customers.first_name,
    customers.last_name,
    min(orders.order_date) as first_order_date,
    max(orders.order_date) as most_recent_order_date,
    count(distinct orders.order_id) as number_of_orders,
    coalesce(sum(payment_totals.total_amount), 0) as lifetime_value
from customers
left join orders on customers.customer_id = orders.customer_id
left join payment_totals on orders.order_id = payment_totals.order_id
group by 1, 2, 3
