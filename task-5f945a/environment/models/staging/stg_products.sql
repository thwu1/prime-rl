select
    product_id,
    product_name,
    category
from {{ source('raw_data', 'products') }}
