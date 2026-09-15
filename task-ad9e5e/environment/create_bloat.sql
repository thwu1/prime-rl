-- Create dead tuples by updating ~20% of rows in each table
-- These updates happen AFTER the prepared transaction, so the prepared
-- transaction's xmin will block vacuum from cleaning these dead tuples

UPDATE orders SET status = 'archived', notes = 'Updated ' || order_id
WHERE order_id % 5 = 0;

UPDATE order_items SET discount = discount + 1.0
WHERE item_id % 5 = 0;

UPDATE audit_log SET new_values = '{"status": "archived"}'::JSONB
WHERE log_id % 5 = 0;

-- Disable autovacuum on audit_log (simulates someone who turned it off
-- during a bulk load and forgot to re-enable it)
ALTER TABLE audit_log SET (autovacuum_enabled = false);
