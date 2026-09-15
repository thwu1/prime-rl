select
    item_id,
    order_id,
    product_id,
    quantity,
    unit_price_cents
from {{ source('raw_data', 'order_items') }}
