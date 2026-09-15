select
    item_id,
    order_id,
    product_id,
    quantity,
    unit_price_cents,
    {{ cents_to_dollars('unit_price_cents') }} as unit_price,
    quantity * {{ cents_to_dollars('unit_price_cents') }} as line_total
from {{ ref('stg_order_items') }}
