-- PostgreSQL benchmark database initialization
-- Creates schema, populates data, and introduces performance anomalies

-- ================================================================
-- SCHEMA
-- ================================================================

CREATE TABLE customers (
    c_id SERIAL PRIMARY KEY,
    c_name VARCHAR(100) NOT NULL,
    c_email VARCHAR(100),
    c_region VARCHAR(50) NOT NULL,
    c_balance DECIMAL(12,2) DEFAULT 0.00,
    c_created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE products (
    p_id SERIAL PRIMARY KEY,
    p_name VARCHAR(200) NOT NULL,
    p_category VARCHAR(100),
    p_brand VARCHAR(100),
    p_price DECIMAL(12,2),
    p_stock INTEGER DEFAULT 0
);

CREATE TABLE orders (
    o_id SERIAL PRIMARY KEY,
    o_customer_id INTEGER NOT NULL,
    o_status VARCHAR(20) NOT NULL,
    o_total DECIMAL(12,2),
    o_created_at TIMESTAMP DEFAULT NOW(),
    o_priority VARCHAR(20) DEFAULT 'medium'
);

CREATE TABLE order_items (
    oi_id SERIAL PRIMARY KEY,
    oi_order_id INTEGER NOT NULL,
    oi_product_id INTEGER NOT NULL,
    oi_quantity INTEGER NOT NULL,
    oi_price DECIMAL(12,2),
    oi_discount DECIMAL(5,2) DEFAULT 0.00
);

CREATE TABLE audit_log (
    al_id SERIAL PRIMARY KEY,
    al_table_name VARCHAR(50) NOT NULL,
    al_operation VARCHAR(10) NOT NULL,
    al_timestamp TIMESTAMP DEFAULT NOW(),
    al_details TEXT
);

-- ================================================================
-- DATA GENERATION
-- ================================================================

-- 10,000 customers
INSERT INTO customers (c_name, c_email, c_region, c_balance, c_created_at)
SELECT
    'Customer_' || i,
    'cust' || i || '@example.com',
    (ARRAY['North America','Europe','Asia Pacific','South America','Africa'])[1 + (i % 5)],
    (random() * 10000)::DECIMAL(12,2),
    TIMESTAMP '2020-01-01' + ((random() * 1460)::INTEGER) * INTERVAL '1 day'
FROM generate_series(1, 10000) AS s(i);

-- 5,000 products
INSERT INTO products (p_name, p_category, p_brand, p_price, p_stock)
SELECT
    'Product_' || i,
    (ARRAY['Electronics','Clothing','Home','Sports','Books','Food','Toys','Auto'])[1 + (i % 8)],
    'Brand_' || (1 + (i % 50)),
    (random() * 500 + 5)::DECIMAL(12,2),
    (random() * 1000)::INTEGER
FROM generate_series(1, 5000) AS s(i);

-- 100,000 orders
INSERT INTO orders (o_customer_id, o_status, o_total, o_created_at, o_priority)
SELECT
    (floor(random() * 10000) + 1)::INTEGER,
    (ARRAY['pending','shipped','delivered','cancelled','returned'])[1 + (i % 5)],
    (random() * 1000 + 10)::DECIMAL(12,2),
    TIMESTAMP '2023-01-01' + ((random() * 730)::INTEGER) * INTERVAL '1 day'
        + ((random() * 86400)::INTEGER) * INTERVAL '1 second',
    (ARRAY['low','medium','high','urgent'])[1 + (i % 4)]
FROM generate_series(1, 100000) AS s(i);

-- 300,000 order items
INSERT INTO order_items (oi_order_id, oi_product_id, oi_quantity, oi_price, oi_discount)
SELECT
    (floor(random() * 100000) + 1)::INTEGER,
    (floor(random() * 5000) + 1)::INTEGER,
    (floor(random() * 10) + 1)::INTEGER,
    (random() * 200 + 5)::DECIMAL(12,2),
    CASE WHEN random() < 0.3 THEN (random() * 20)::DECIMAL(5,2) ELSE 0.00 END
FROM generate_series(1, 300000) AS s(i);

-- 100,000 audit log entries
INSERT INTO audit_log (al_table_name, al_operation, al_timestamp, al_details)
SELECT
    (ARRAY['orders','customers','products','order_items'])[1 + (i % 4)],
    (ARRAY['INSERT','UPDATE','DELETE','SELECT'])[1 + (i % 4)],
    TIMESTAMP '2023-06-01' + ((random() * 365)::INTEGER) * INTERVAL '1 day',
    'Operation on record ' || i || ' by user_' || (1 + (i % 20))
FROM generate_series(1, 100000) AS s(i);

-- Collect optimizer statistics on all populated tables
ANALYZE;

-- ================================================================
-- INTRODUCE PERFORMANCE ANOMALIES
-- ================================================================

-- ANOMALY: Missing indexes on heavily queried columns
-- orders.o_customer_id, orders.o_status, order_items.oi_order_id, order_items.oi_product_id
-- are all used in frequent joins and filters but have NO indexes.
-- (Intentionally not created here.)

-- ANOMALY: Redundant indexes on customers table
-- idx_cust_region is a strict prefix of both composite indexes and wastes write throughput
CREATE INDEX idx_cust_region ON customers(c_region);
CREATE INDEX idx_cust_region_name ON customers(c_region, c_name);
CREATE INDEX idx_cust_region_balance ON customers(c_region, c_balance);

-- ANOMALY: Table bloat from unvacuumed deletes
ALTER TABLE audit_log SET (autovacuum_enabled = false);
DELETE FROM audit_log WHERE al_id <= 80000;
-- Allow stats counters to flush
SELECT pg_sleep(2);

-- ANOMALY: Suboptimal PostgreSQL configuration knobs
ALTER SYSTEM SET shared_buffers = '16MB';
ALTER SYSTEM SET work_mem = '256kB';
ALTER SYSTEM SET maintenance_work_mem = '2MB';
ALTER SYSTEM SET effective_cache_size = '64MB';
ALTER SYSTEM SET random_page_cost = 4.0;

-- ANOMALY: View with correlated subqueries (O(N*M) performance)
CREATE VIEW v_customer_order_summary AS
SELECT c.c_id, c.c_name, c.c_region,
    (SELECT COUNT(*) FROM orders o WHERE o.o_customer_id = c.c_id) AS order_count,
    (SELECT COALESCE(SUM(o.o_total), 0) FROM orders o WHERE o.o_customer_id = c.c_id) AS total_spent,
    (SELECT MAX(o.o_created_at) FROM orders o WHERE o.o_customer_id = c.c_id) AS last_order
FROM customers c;
