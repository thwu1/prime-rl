with orders as (
    select * from {{ ref('stg_orders') }}
),

payments as (
    select * from {{ ref('int_payment_type_amounts') }}
)

select
    orders.order_id,
    orders.customer_id,
    orders.order_date,
    orders.status,
    {% for method in var('pay_methods') %}
    payments.{{ method }}_amount,
    {% endfor %}
    payments.total_amount
from orders
left join payments on orders.order_id = payments.order_id
