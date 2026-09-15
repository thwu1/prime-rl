-- Q4: Top-rated electronics products
SELECT *
FROM product_summary
WHERE category = 'Electronics'
ORDER BY avg_rating DESC NULLS LAST
LIMIT 20;
