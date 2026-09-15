
-- Enable extensions
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- ===========================================
-- Schema
-- ===========================================

CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    country VARCHAR(2) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    status VARCHAR(20) DEFAULT 'active'
);

CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    stock INT DEFAULT 0
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES customers(id),
    order_date TIMESTAMP NOT NULL DEFAULT NOW(),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    total DECIMAL(10,2) NOT NULL,
    shipping_country VARCHAR(2)
);

CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES orders(id),
    product_id INT NOT NULL REFERENCES products(id),
    quantity INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    discount DECIMAL(5,2) DEFAULT 0
);

-- ===========================================
-- Data generation
-- ===========================================

INSERT INTO customers (email, name, country, created_at, status)
SELECT
    'user' || i || '@example.com',
    'Customer ' || i,
    (ARRAY['US','UK','DE','FR','JP','CA','AU','BR','IN','MX'])[1 + (i % 10)],
    NOW() - ((random() * 730)::int || ' days')::interval,
    CASE WHEN random() < 0.9 THEN 'active' ELSE 'inactive' END
FROM generate_series(1, 10000) i;

INSERT INTO products (sku, name, category, price, stock)
SELECT
    'SKU-' || lpad(i::text, 5, '0'),
    'Product ' || i,
    (ARRAY['electronics','clothing','books','home','sports'])[1 + (i % 5)],
    round((random() * 500 + 5)::numeric, 2),
    (random() * 1000)::int
FROM generate_series(1, 1000) i;

INSERT INTO orders (customer_id, order_date, status, total, shipping_country)
SELECT
    1 + (random() * 9999)::int,
    NOW() - ((random() * 730)::int || ' days')::interval,
    (ARRAY[
        'completed','completed','completed','completed','completed','completed','completed',
        'shipped','shipped','shipped','shipped',
        'pending',
        'cancelled'
    ])[1 + (i % 13)],
    round((random() * 500 + 10)::numeric, 2),
    (ARRAY['US','UK','DE','FR','JP','CA','AU','BR','IN','MX'])[1 + (i % 10)]
FROM generate_series(1, 100000) i;

INSERT INTO order_items (order_id, product_id, quantity, unit_price, discount)
SELECT
    1 + (i / 4),
    1 + (random() * 999)::int,
    1 + (random() * 5)::int,
    round((random() * 200 + 5)::numeric, 2),
    CASE WHEN random() < 0.2 THEN round((random() * 30)::numeric, 2) ELSE 0 END
FROM generate_series(0, 399999) i;

-- ===========================================
-- Indexes: useful (KEEP)
-- ===========================================
CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_date_status ON orders(order_date, status);
CREATE INDEX idx_oi_order_id ON order_items(order_id);
CREATE INDEX idx_oi_product_id ON order_items(product_id);
CREATE INDEX idx_products_category ON products(category);
CREATE INDEX idx_customers_country ON customers(country);

-- ===========================================
-- Indexes: exact duplicates (should be DROPPED)
-- ===========================================
CREATE INDEX idx_orders_customer_id_dup ON orders(customer_id);
CREATE INDEX idx_oi_order_id_copy ON order_items(order_id);
CREATE INDEX idx_oi_product_id_dup ON order_items(product_id);

-- ===========================================
-- Index: prefix-redundant (should be DROPPED)
-- Covered by idx_orders_date_status via B-tree left-prefix rule
-- ===========================================
CREATE INDEX idx_orders_date_only ON orders(order_date);

-- ===========================================
-- Indexes: unused / never queried (should be DROPPED)
-- ===========================================
CREATE INDEX idx_orders_shipping_country ON orders(shipping_country);
CREATE INDEX idx_orders_total ON orders(total);
CREATE INDEX idx_oi_quantity ON order_items(quantity);
CREATE INDEX idx_oi_discount ON order_items(discount);
CREATE INDEX idx_oi_unit_price ON order_items(unit_price);
CREATE INDEX idx_customers_status ON customers(status);
CREATE INDEX idx_customers_name ON customers(name);

-- Update planner statistics
ANALYZE;
