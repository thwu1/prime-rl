select
    o.order_date,
    p.category,
    sum(r.line_total) as total_revenue,
    count(distinct o.order_id) as order_count
from {{ ref('stg_orders') }} o
inner join {{ ref('int_order_revenue') }} r
    on o.order_id = r.item_id
inner join {{ ref('stg_products') }} p
    on r.product_id = p.product_id
where o.status = 'complete'
group by 1, 2
