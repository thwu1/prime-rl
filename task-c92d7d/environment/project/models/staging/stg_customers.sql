with source as (
    select * from {{ source('ecommerce', 'raw_customers') }}
),

renamed as (
    select
        id as customer_id,
        first_name,
        last_name,
        email,
        created_at,
        updated_at
    from source
)

select * from renamed
