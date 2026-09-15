with payments as (
    select * from {{ ref('stg_payments') }}
),

orders as (
    select * from {{ ref('stg_orders') }}
),

customer_history as (
    select * from {{ ref('int_customer_order_history') }}
)

select
    orders.order_id,
    orders.customer_id,
    customer_history.first_order_date,
    sum(case when payments.payment_method = 'credit_card' then payments.amount else 0 end) as credit_card_amount,
    sum(case when payments.payment_method = 'bank_transfer' then payments.amount else 0 end) as bank_transfer_amount,
    sum(case when payments.payment_method = 'coupon' then payments.amount else 0 end) as coupon_amount,
    sum(payments.amount) as total_amount
from payments
left join orders on payments.order_id = orders.order_id
left join customer_history on orders.customer_id = customer_history.customer_id
group by 1, 2, 3
