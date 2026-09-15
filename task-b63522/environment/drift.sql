-- Schema drift: unauthorized manual DBA interventions
ALTER TABLE customers ALTER COLUMN name TYPE TEXT;
CREATE INDEX idx_orders_created ON orders(created_at);
ALTER TABLE products ALTER COLUMN price SET DEFAULT 0.00;
