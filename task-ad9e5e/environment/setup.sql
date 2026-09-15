-- Schema and data setup for e-commerce database
-- Creates tables, inserts data, installs pgstattuple extension

CREATE EXTENSION IF NOT EXISTS pgstattuple;

CREATE TABLE orders (
    order_id SERIAL PRIMARY KEY,
    customer_id INT NOT NULL,
    order_date TIMESTAMP NOT NULL DEFAULT NOW(),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    total_amount NUMERIC(12,2) NOT NULL,
    shipping_address TEXT,
    notes TEXT
);

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_amount ON orders(total_amount);
CREATE INDEX idx_orders_customer_date ON orders(customer_id, order_date);

CREATE TABLE order_items (
    item_id SERIAL PRIMARY KEY,
    order_id INT NOT NULL,
    product_name VARCHAR(200) NOT NULL,
    quantity INT NOT NULL,
    unit_price NUMERIC(10,2) NOT NULL,
    discount NUMERIC(5,2) DEFAULT 0
);

CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_items_product ON order_items(product_name);

CREATE TABLE audit_log (
    log_id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    table_name VARCHAR(100),
    record_id INT,
    old_values JSONB,
    new_values JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    user_id INT
);

CREATE INDEX idx_audit_event ON audit_log(event_type);

-- Insert 300K orders
INSERT INTO orders (customer_id, order_date, status, total_amount, shipping_address, notes)
SELECT
    (random() * 10000)::INT,
    NOW() - (random() * 365)::INT * INTERVAL '1 day',
    CASE (random() * 4)::INT
        WHEN 0 THEN 'pending'
        WHEN 1 THEN 'processing'
        WHEN 2 THEN 'shipped'
        WHEN 3 THEN 'delivered'
        ELSE 'cancelled'
    END,
    (random() * 10000)::NUMERIC(12,2),
    'Address ' || g,
    'Notes for order ' || g
FROM generate_series(1, 300000) g;

-- Insert 600K order items
INSERT INTO order_items (order_id, product_name, quantity, unit_price, discount)
SELECT
    (g % 300000) + 1,
    'Product ' || (random() * 1000)::INT,
    (random() * 10 + 1)::INT,
    (random() * 100)::NUMERIC(10,2),
    (random() * 20)::NUMERIC(5,2)
FROM generate_series(1, 600000) g;

-- Insert 100K audit log entries
INSERT INTO audit_log (event_type, table_name, record_id, old_values, new_values, created_at, user_id)
SELECT
    CASE (random() * 3)::INT
        WHEN 0 THEN 'INSERT'
        WHEN 1 THEN 'UPDATE'
        WHEN 2 THEN 'DELETE'
        ELSE 'SELECT'
    END,
    CASE (random() * 2)::INT
        WHEN 0 THEN 'orders'
        WHEN 1 THEN 'order_items'
        ELSE 'audit_log'
    END,
    g,
    '{"status": "old"}'::JSONB,
    '{"status": "new"}'::JSONB,
    NOW() - (random() * 30)::INT * INTERVAL '1 day',
    (random() * 100)::INT
FROM generate_series(1, 100000) g;

ANALYZE orders;
ANALYZE order_items;
ANALYZE audit_log;
