-- Create an orphaned prepared transaction that will block the vacuum xmin horizon
-- This simulates a failed two-phase commit from a migration that was never cleaned up
BEGIN;
UPDATE orders SET notes = 'migration_temp_20240115' WHERE order_id = 1;
PREPARE TRANSACTION 'failed_migration_20240115';
