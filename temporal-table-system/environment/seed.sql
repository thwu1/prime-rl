-- seed.sql — Test tables for temporal versioning
--

-- Single-column primary key
CREATE TABLE IF NOT EXISTS products (
    product_id SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    price      NUMERIC(10,2) NOT NULL,
    category   TEXT,
    is_active  BOOLEAN DEFAULT true
);

-- Composite primary key
CREATE TABLE IF NOT EXISTS order_items (
    order_id   INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity   INTEGER NOT NULL,
    unit_price NUMERIC(10,2) NOT NULL,
    PRIMARY KEY (order_id, product_id)
);

-- No primary key (enable_versioning must reject this)
CREATE TABLE IF NOT EXISTS log_entries (
    message    TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Seed data
INSERT INTO products (name, price, category, is_active) VALUES
    ('Laptop', 999.99, 'electronics', true),
    ('Mouse',   29.99, 'electronics', true),
    ('Desk',   449.99, 'furniture',   true);

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
    (1, 1, 1, 999.99),
    (1, 2, 2,  29.99),
    (2, 3, 1, 449.99);
