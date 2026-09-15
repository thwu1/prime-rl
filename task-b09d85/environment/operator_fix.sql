-- Operator's manual attempt to fix the failed V3 migration.
-- Applied ad-hoc without consulting the migration files.

ALTER TABLE orders ADD COLUMN shipping_address TEXT;
ALTER TABLE orders ADD COLUMN tracking_number VARCHAR(100);

-- Operator also created utility objects while debugging the incident
CREATE OR REPLACE FUNCTION calc_order_total(order_id_param INTEGER)
RETURNS DECIMAL AS $$
    SELECT COALESCE(SUM(unit_price * quantity), 0)
    FROM order_items WHERE order_id = order_id_param;
$$ LANGUAGE SQL;

CREATE VIEW shipping_report AS
    SELECT o.id AS order_id, u.username, o.total, o.shipping_address, o.tracking_number
    FROM orders o JOIN users u ON o.user_id = u.id;

CREATE INDEX idx_orders_pending ON orders(created_at) WHERE status = 'pending';
