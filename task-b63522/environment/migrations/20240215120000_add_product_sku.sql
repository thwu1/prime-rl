ALTER TABLE products ADD COLUMN sku VARCHAR(50) UNIQUE;

CREATE INDEX idx_orders_status ON orders(status);
