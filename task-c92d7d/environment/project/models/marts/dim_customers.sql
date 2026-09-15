with customer_history as (
    select * from {{ ref('int_customer_order_history') }}
),

payment_amounts as (
    select
        customer_id,
        sum(total_amount) as lifetime_value
    from {{ ref('int_payment_type_amounts') }}
    group by 1
),

customers as (
    select * from {{ ref('stg_customers') }}
)

select
    customer_history.customer_id,
    customer_history.first_name,
    customer_history.last_name,
    customers.email,
    customer_history.first_order_date,
    customer_history.most_recent_order_date,
    customer_history.number_of_orders,
    coalesce(payment_amounts.lifetime_value, 0) as lifetime_value
from customer_history
left join customers on customer_history.customer_id = customers.customer_id
left join payment_amounts on customer_history.customer_id = payment_amounts.customer_id
