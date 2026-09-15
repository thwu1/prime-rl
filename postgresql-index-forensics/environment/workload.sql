
-- Reset statistics so only this workload's patterns are reflected
SELECT pg_stat_reset();
SELECT pg_stat_statements_reset();

-- Pattern 1: Customer order lookups (uses idx_orders_customer_id)
DO $$
BEGIN
    FOR i IN 1..500 LOOP
        PERFORM * FROM orders WHERE customer_id = 1 + (i % 10000);
    END LOOP;
END $$;

-- Pattern 2: Order line-item lookups (uses idx_oi_order_id)
DO $$
BEGIN
    FOR i IN 1..500 LOOP
        PERFORM * FROM order_items WHERE order_id = 1 + (i % 100000);
    END LOOP;
END $$;

-- Pattern 3: Product item lookups (uses idx_oi_product_id)
DO $$
BEGIN
    FOR i IN 1..500 LOOP
        PERFORM * FROM order_items WHERE product_id = 1 + (i % 1000);
    END LOOP;
END $$;

-- Pattern 4: Date-range + status queries (uses idx_orders_date_status)
DO $$
BEGIN
    FOR i IN 1..300 LOOP
        PERFORM * FROM orders
        WHERE order_date > NOW() - ((i * 2) || ' days')::interval
          AND status = 'completed';
    END LOOP;
END $$;

-- Pattern 5: Product category lookups (uses idx_products_category)
DO $$
DECLARE
    cats TEXT[] := ARRAY['electronics','clothing','books','home','sports'];
BEGIN
    FOR i IN 1..200 LOOP
        PERFORM * FROM products WHERE category = cats[1 + (i % 5)];
    END LOOP;
END $$;

-- Pattern 6: Country-based customer lookups (uses idx_customers_country)
DO $$
DECLARE
    countries TEXT[] := ARRAY['US','UK','DE','FR','JP','CA','AU','BR','IN','MX'];
BEGIN
    FOR i IN 1..200 LOOP
        PERFORM * FROM customers WHERE country = countries[1 + (i % 10)];
    END LOOP;
END $$;

-- Pattern 7: Pending orders dashboard (SLOW - no suitable index exists)
-- This query filters by status='pending' (~8% of orders) and sorts by date.
-- The existing composite idx_orders_date_status has order_date first,
-- so it cannot efficiently serve status-only filters.
DO $$
BEGIN
    FOR i IN 1..100 LOOP
        PERFORM o.id, o.order_date, o.total, c.name
        FROM orders o
        JOIN customers c ON o.customer_id = c.id
        WHERE o.status = 'pending'
        ORDER BY o.order_date DESC
        LIMIT 50;
    END LOOP;
END $$;

-- Flush accumulated stats to shared memory
SELECT pg_stat_force_next_flush();
