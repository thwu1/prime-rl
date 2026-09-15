-- Paginated sales listing: deep pagination to page ~5000
SELECT sale_id, sale_date, eur_value, product_id
FROM sales
ORDER BY sale_date DESC, sale_id DESC
LIMIT 10 OFFSET 50000;
