with source as (
    select * from {{ source('ecommerce', 'raw_orders') }}
),

renamed as (
    select
        id as order_id,
        customer_id,
        order_date,
        status
    from source
)

select * from renamed
