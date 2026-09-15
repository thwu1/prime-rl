-- atlas:txmode none

CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL
);

ALTER TABLE customers ADD COLUMN phone VARCHAR(20);

ALTER TABLE orders ADD COLUMN shipping_address VARCHAR(255) NOT NULL;

CREATE INDEX CONCURRENTLY idx_customers_email ON customers(email);
