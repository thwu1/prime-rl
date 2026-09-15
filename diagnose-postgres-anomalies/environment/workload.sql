-- PRODUCTION WORKLOAD SPECIFICATION
-- Representative queries and their peak-hour execution frequencies.
-- Use this to inform index and configuration optimization decisions.

-- Q1: Customer order lookup (Frequency: 500/hr)
-- SELECT o_id, o_status, o_total, o_created_at
-- FROM orders WHERE o_customer_id = $1;

-- Q2: Pending orders with customer info (Frequency: 300/hr)
-- SELECT o.o_id, o.o_total, c.c_name, c.c_email
-- FROM orders o
-- JOIN customers c ON o.o_customer_id = c.c_id
-- WHERE o.o_status = 'pending';

-- Q3: Order line items with product details (Frequency: 400/hr)
-- SELECT oi.oi_quantity, oi.oi_price, p.p_name, p.p_category
-- FROM order_items oi
-- JOIN products p ON oi.oi_product_id = p.p_id
-- WHERE oi.oi_order_id = $1;

-- Q4: Product revenue aggregation (Frequency: 100/hr)
-- SELECT p.p_id, p.p_name,
--        SUM(oi.oi_quantity) AS total_sold,
--        SUM(oi.oi_price * oi.oi_quantity) AS revenue
-- FROM order_items oi
-- JOIN products p ON oi.oi_product_id = p.p_id
-- GROUP BY p.p_id, p.p_name
-- ORDER BY revenue DESC LIMIT 20;

-- Q5: Customer summary dashboard (Frequency: 200/hr) — KNOWN SLOW
-- SELECT * FROM v_customer_order_summary
-- WHERE c_region = 'North America';

-- Q6: Regional customer search (Frequency: 150/hr)
-- SELECT c_id, c_name, c_balance
-- FROM customers
-- WHERE c_region = 'Europe' AND c_balance > 5000;

-- Q7: Customer balance update (Frequency: 250/hr)
-- UPDATE customers SET c_balance = c_balance + $1 WHERE c_id = $2;

-- Q8: New order insertion (Frequency: 200/hr)
-- INSERT INTO orders (o_customer_id, o_status, o_total, o_created_at, o_priority)
-- VALUES ($1, 'pending', $2, NOW(), $3);

-- Q9: Recent audit log query (Frequency: 50/hr)
-- SELECT * FROM audit_log
-- WHERE al_table_name = 'orders'
--   AND al_timestamp > NOW() - INTERVAL '24 hours'
-- ORDER BY al_timestamp DESC LIMIT 100;

-- Q10: High-priority pending orders (Frequency: 180/hr)
-- SELECT o.o_id, o.o_total, o.o_priority, c.c_name
-- FROM orders o
-- JOIN customers c ON o.o_customer_id = c.c_id
-- WHERE o.o_priority = 'urgent' AND o.o_status = 'pending';
