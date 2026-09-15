{{
    config(
        materialized='incremental',
        unique_key='date',
        incremental_strategy='delete+insert'
    )
}}

with orders as (
    select * from {{ ref('stg_orders') }}
),

payments as (
    select * from {{ ref('stg_payments') }}
)

select
    orders.order_date,
    count(distinct orders.order_id) as total_orders,
    sum(payments.amount) as total_revenue
from orders
left join payments on orders.order_id = payments.order_id

{% if is_incremental() %}
    where orders._loaded_at > (select max(_loaded_at) from {{ this }})
{% endif %}

group by 1
