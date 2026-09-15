-- PostgreSQL Performance Diagnosis Challenge - Database Setup

-- ========== SCHEMA ==========

CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(200),
    region VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    category VARCHAR(50) NOT NULL,
    price NUMERIC(10,2) NOT NULL,
    stock_qty INT DEFAULT 0
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES customers(id),
    order_date TIMESTAMP NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    total_amount NUMERIC(12,2) NOT NULL
);

CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES orders(id),
    product_id INT NOT NULL REFERENCES products(id),
    quantity INT NOT NULL,
    unit_price NUMERIC(10,2) NOT NULL
);

CREATE TABLE reviews (
    id SERIAL PRIMARY KEY,
    product_id INT NOT NULL REFERENCES products(id),
    customer_id INT NOT NULL REFERENCES customers(id),
    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    review_text TEXT,
    created_at TIMESTAMP DEFAULT now()
);

-- ========== DATA GENERATION ==========

-- 5,000 customers
INSERT INTO customers (name, email, region)
SELECT
    'Customer_' || i,
    'customer' || i || '@example.com',
    (ARRAY['North', 'South', 'East', 'West', 'Central'])[1 + (i % 5)]
FROM generate_series(1, 5000) AS s(i);

-- 1,000 products across 10 categories
INSERT INTO products (name, category, price, stock_qty)
SELECT
    'Product_' || i,
    (ARRAY['Electronics', 'Clothing', 'Books', 'Home', 'Sports',
           'Food', 'Toys', 'Auto', 'Health', 'Garden'])[1 + (i % 10)],
    ROUND((10 + (i * 31 % 490))::numeric, 2),
    (i * 13 % 500)
FROM generate_series(1, 1000) AS s(i);

-- 200,000 orders (will delete 120K to create bloat)
INSERT INTO orders (customer_id, order_date, status, total_amount)
SELECT
    1 + (i % 5000),
    '2023-01-01'::timestamp
        + ((i * 17 % 365) * interval '1 day')
        + ((i * 7 % 1440) * interval '1 minute'),
    (ARRAY['completed', 'pending', 'shipped', 'cancelled'])[1 + (i % 4)],
    ROUND((10 + (i * 31 % 990))::numeric, 2)
FROM generate_series(1, 200000) AS s(i);

-- ========== ANTI-PATTERN: DISABLE AUTOVACUUM BEFORE CREATING BLOAT ==========
ALTER SYSTEM SET autovacuum = off;
SELECT pg_reload_conf();

-- Create bloat: delete first 120,000 orders (no order_items reference them yet)
DELETE FROM orders WHERE id <= 120000;
-- DO NOT VACUUM -- dead tuples create intentional table bloat

-- 240,000 order_items (3 per surviving order)
INSERT INTO order_items (order_id, product_id, quantity, unit_price)
SELECT
    o.id,
    1 + ((o.id * 7 + gs.n) % 1000),
    1 + ((o.id + gs.n) % 5),
    ROUND((5 + ((o.id * 3 + gs.n * 11) % 200))::numeric, 2)
FROM orders o
CROSS JOIN generate_series(1, 3) AS gs(n);

-- 20,000 reviews
INSERT INTO reviews (product_id, customer_id, rating, review_text, created_at)
SELECT
    1 + (i % 1000),
    1 + (i % 5000),
    1 + (i % 5),
    'Review text for product ' || (1 + (i % 1000)),
    '2023-01-01'::timestamp + ((i * 13 % 365) * interval '1 day')
FROM generate_series(1, 20000) AS s(i);

-- ========== STATISTICS (deliberately skip ANALYZE on orders) ==========
ANALYZE customers;
ANALYZE products;
ANALYZE order_items;
ANALYZE reviews;

-- ========== ANTI-PATTERN: CORRELATED SUBQUERY VIEW ==========
CREATE VIEW product_summary AS
SELECT p.id, p.name, p.category, p.price,
    (SELECT AVG(r.rating) FROM reviews r WHERE r.product_id = p.id) AS avg_rating,
    (SELECT COUNT(*) FROM reviews r WHERE r.product_id = p.id) AS review_count,
    (SELECT COALESCE(SUM(oi.quantity), 0) FROM order_items oi WHERE oi.product_id = p.id) AS total_sold
FROM products p;

-- ========== ANTI-PATTERN: BAD CONFIGURATION ==========
ALTER SYSTEM SET work_mem = '64kB';
ALTER SYSTEM SET random_page_cost = 4.0;
ALTER SYSTEM SET effective_cache_size = '64MB';
SELECT pg_reload_conf();
