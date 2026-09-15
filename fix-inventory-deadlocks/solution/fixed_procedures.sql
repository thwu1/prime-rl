
-- Fixed stored procedures for inventory reservation system

---------------------------------------------------------------------
-- reserve_order_stock: Reserve inventory for all lines in an order
-- FIX: Added ORDER BY product_id, warehouse_id to ensure deterministic
--      lock acquisition order, preventing deadlocks when concurrent
--      orders reference overlapping products.
---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION reserve_order_stock(p_order_id INT)
RETURNS BOOLEAN AS $$
DECLARE
    v_line RECORD;
    v_available INT;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM orders WHERE order_id = p_order_id AND status = 'PENDING'
    ) THEN
        RAISE EXCEPTION 'Order % is not in PENDING status', p_order_id;
    END IF;

    FOR v_line IN
        SELECT ol.line_id, ol.product_id, ol.warehouse_id, ol.quantity
        FROM order_lines ol
        WHERE ol.order_id = p_order_id
        ORDER BY ol.product_id, ol.warehouse_id
    LOOP
        SELECT quantity_on_hand - quantity_reserved
        INTO v_available
        FROM inventory
        WHERE product_id = v_line.product_id
          AND warehouse_id = v_line.warehouse_id
        FOR UPDATE;

        IF v_available IS NULL THEN
            RAISE EXCEPTION 'No inventory record for product % in warehouse %',
                v_line.product_id, v_line.warehouse_id;
        END IF;

        IF v_available < v_line.quantity THEN
            RAISE EXCEPTION 'Insufficient stock for product % in warehouse %: available=%, requested=%',
                v_line.product_id, v_line.warehouse_id, v_available, v_line.quantity;
        END IF;

        UPDATE inventory
        SET quantity_reserved = quantity_reserved + v_line.quantity,
            last_updated = NOW()
        WHERE product_id = v_line.product_id
          AND warehouse_id = v_line.warehouse_id;

        INSERT INTO reservations (order_id, product_id, warehouse_id, quantity, status)
        VALUES (p_order_id, v_line.product_id, v_line.warehouse_id, v_line.quantity, 'ACTIVE');

        INSERT INTO stock_movements (product_id, warehouse_id, movement_type, quantity, reference_id)
        VALUES (v_line.product_id, v_line.warehouse_id, 'RESERVATION', v_line.quantity, p_order_id);
    END LOOP;

    UPDATE orders SET status = 'RESERVED', processed_at = NOW()
    WHERE order_id = p_order_id;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;


---------------------------------------------------------------------
-- cancel_order: Cancel a reserved order and release stock
-- FIXES:
--   1. Added FOR UPDATE on the order status check to prevent
--      concurrent cancel races and cancel/fulfill/reallocate races.
--   2. Added UPDATE reservations SET status = 'RELEASED' for each
--      processed reservation to prevent double-release and maintain
--      the quantity_reserved invariant.
---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION cancel_order(p_order_id INT)
RETURNS BOOLEAN AS $$
DECLARE
    v_status VARCHAR;
    v_res RECORD;
BEGIN
    SELECT status INTO v_status
    FROM orders
    WHERE order_id = p_order_id
    FOR UPDATE;

    IF v_status IS NULL THEN
        RAISE EXCEPTION 'Order % not found', p_order_id;
    END IF;

    IF v_status != 'RESERVED' THEN
        RAISE EXCEPTION 'Order % is not in RESERVED status (current: %)',
            p_order_id, v_status;
    END IF;

    FOR v_res IN
        SELECT reservation_id, product_id, warehouse_id, quantity
        FROM reservations
        WHERE order_id = p_order_id AND status = 'ACTIVE'
    LOOP
        UPDATE inventory
        SET quantity_reserved = quantity_reserved - v_res.quantity,
            last_updated = NOW()
        WHERE product_id = v_res.product_id
          AND warehouse_id = v_res.warehouse_id;

        UPDATE reservations
        SET status = 'RELEASED'
        WHERE reservation_id = v_res.reservation_id;

        INSERT INTO stock_movements (product_id, warehouse_id, movement_type, quantity, reference_id)
        VALUES (v_res.product_id, v_res.warehouse_id, 'RELEASE', v_res.quantity, p_order_id);
    END LOOP;

    UPDATE orders SET status = 'CANCELLED', processed_at = NOW()
    WHERE order_id = p_order_id;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;


---------------------------------------------------------------------
-- fulfill_order: Ship a reserved order, deducting on-hand stock
-- FIXES:
--   1. Added FOR UPDATE on order status check to prevent concurrent
--      cancel/fulfill/reallocate races.
--   2. Added ORDER BY product_id, warehouse_id to the reservation
--      cursor to ensure deterministic lock acquisition order.
--   3. Added UPDATE reservations SET status = 'FULFILLED' for each
--      processed reservation.
---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fulfill_order(p_order_id INT)
RETURNS BOOLEAN AS $$
DECLARE
    v_status VARCHAR;
    v_res RECORD;
BEGIN
    SELECT status INTO v_status
    FROM orders
    WHERE order_id = p_order_id
    FOR UPDATE;

    IF v_status IS NULL THEN
        RAISE EXCEPTION 'Order % not found', p_order_id;
    END IF;

    IF v_status != 'RESERVED' THEN
        RAISE EXCEPTION 'Order % is not in RESERVED status (current: %)',
            p_order_id, v_status;
    END IF;

    FOR v_res IN
        SELECT reservation_id, product_id, warehouse_id, quantity
        FROM reservations
        WHERE order_id = p_order_id AND status = 'ACTIVE'
        ORDER BY product_id, warehouse_id
    LOOP
        UPDATE inventory
        SET quantity_on_hand = quantity_on_hand - v_res.quantity,
            quantity_reserved = quantity_reserved - v_res.quantity,
            last_updated = NOW()
        WHERE product_id = v_res.product_id
          AND warehouse_id = v_res.warehouse_id;

        UPDATE reservations
        SET status = 'FULFILLED'
        WHERE reservation_id = v_res.reservation_id;

        INSERT INTO stock_movements (product_id, warehouse_id, movement_type, quantity, reference_id)
        VALUES (v_res.product_id, v_res.warehouse_id, 'SHIPMENT', v_res.quantity, p_order_id);
    END LOOP;

    UPDATE orders SET status = 'SHIPPED', processed_at = NOW()
    WHERE order_id = p_order_id;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;


---------------------------------------------------------------------
-- transfer_stock: Move unreserved stock between warehouses
-- FIXES:
--   1. Lock both inventory rows in deterministic order (by warehouse_id)
--      using SELECT FOR UPDATE before any modifications.
--   2. Check available stock AFTER locking to close the TOCTOU race.
---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION transfer_stock(
    p_product_id INT,
    p_from_warehouse_id INT,
    p_to_warehouse_id INT,
    p_quantity INT
) RETURNS BOOLEAN AS $$
DECLARE
    v_src_on_hand INT;
    v_src_reserved INT;
    v_available INT;
    v_first_wh INT;
    v_second_wh INT;
BEGIN
    IF p_quantity <= 0 THEN
        RAISE EXCEPTION 'Transfer quantity must be positive';
    END IF;

    IF p_from_warehouse_id = p_to_warehouse_id THEN
        RAISE EXCEPTION 'Cannot transfer to same warehouse';
    END IF;

    -- Ensure destination inventory record exists before locking
    INSERT INTO inventory (product_id, warehouse_id, quantity_on_hand, quantity_reserved)
    VALUES (p_product_id, p_to_warehouse_id, 0, 0)
    ON CONFLICT (product_id, warehouse_id) DO NOTHING;

    -- Determine deterministic lock order by warehouse_id
    IF p_from_warehouse_id < p_to_warehouse_id THEN
        v_first_wh := p_from_warehouse_id;
        v_second_wh := p_to_warehouse_id;
    ELSE
        v_first_wh := p_to_warehouse_id;
        v_second_wh := p_from_warehouse_id;
    END IF;

    -- Lock first warehouse row
    PERFORM 1 FROM inventory
    WHERE product_id = p_product_id AND warehouse_id = v_first_wh
    FOR UPDATE;

    -- Lock second warehouse row
    PERFORM 1 FROM inventory
    WHERE product_id = p_product_id AND warehouse_id = v_second_wh
    FOR UPDATE;

    -- Now read source values (both rows are locked, values are stable)
    SELECT quantity_on_hand, quantity_reserved
    INTO v_src_on_hand, v_src_reserved
    FROM inventory
    WHERE product_id = p_product_id AND warehouse_id = p_from_warehouse_id;

    IF v_src_on_hand IS NULL THEN
        RAISE EXCEPTION 'No inventory record for product % in warehouse %',
            p_product_id, p_from_warehouse_id;
    END IF;

    v_available := v_src_on_hand - v_src_reserved;

    IF v_available < p_quantity THEN
        RAISE EXCEPTION 'Insufficient available stock: available=%, requested=%',
            v_available, p_quantity;
    END IF;

    -- Perform the transfer
    UPDATE inventory
    SET quantity_on_hand = quantity_on_hand - p_quantity,
        last_updated = NOW()
    WHERE product_id = p_product_id AND warehouse_id = p_from_warehouse_id;

    UPDATE inventory
    SET quantity_on_hand = quantity_on_hand + p_quantity,
        last_updated = NOW()
    WHERE product_id = p_product_id AND warehouse_id = p_to_warehouse_id;

    INSERT INTO stock_movements (product_id, warehouse_id, movement_type, quantity, reference_id)
    VALUES (p_product_id, p_from_warehouse_id, 'TRANSFER_OUT', p_quantity, NULL);

    INSERT INTO stock_movements (product_id, warehouse_id, movement_type, quantity, reference_id)
    VALUES (p_product_id, p_to_warehouse_id, 'TRANSFER_IN', p_quantity, NULL);

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;


---------------------------------------------------------------------
-- reallocate_reservation: Move a reservation between warehouses
-- FIXES:
--   1. Lock order row FOR UPDATE to serialize with cancel/fulfill.
--   2. Lock both inventory rows in deterministic warehouse_id order
--      using SELECT FOR UPDATE to prevent deadlocks.
--   3. Check destination availability AFTER locking to close TOCTOU.
--   4. Update reservation record's warehouse_id so that downstream
--      cancel_order and fulfill_order operate on the correct
--      inventory rows.
---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION reallocate_reservation(
    p_order_id INT,
    p_product_id INT,
    p_from_warehouse_id INT,
    p_to_warehouse_id INT
) RETURNS BOOLEAN AS $$
DECLARE
    v_status VARCHAR;
    v_res_id INT;
    v_qty INT;
    v_available INT;
    v_first_wh INT;
    v_second_wh INT;
BEGIN
    IF p_from_warehouse_id = p_to_warehouse_id THEN
        RAISE EXCEPTION 'Source and destination warehouses must differ';
    END IF;

    -- Lock order row to serialize with cancel/fulfill
    SELECT status INTO v_status
    FROM orders
    WHERE order_id = p_order_id
    FOR UPDATE;

    IF v_status IS NULL THEN
        RAISE EXCEPTION 'Order % not found', p_order_id;
    END IF;

    IF v_status != 'RESERVED' THEN
        RAISE EXCEPTION 'Order % is not in RESERVED status (current: %)',
            p_order_id, v_status;
    END IF;

    -- Find the active reservation to move
    SELECT reservation_id, quantity INTO v_res_id, v_qty
    FROM reservations
    WHERE order_id = p_order_id
      AND product_id = p_product_id
      AND warehouse_id = p_from_warehouse_id
      AND status = 'ACTIVE';

    IF v_res_id IS NULL THEN
        RAISE EXCEPTION 'No active reservation found for order %, product %, warehouse %',
            p_order_id, p_product_id, p_from_warehouse_id;
    END IF;

    -- Lock both inventory rows in deterministic warehouse_id order
    IF p_from_warehouse_id < p_to_warehouse_id THEN
        v_first_wh := p_from_warehouse_id;
        v_second_wh := p_to_warehouse_id;
    ELSE
        v_first_wh := p_to_warehouse_id;
        v_second_wh := p_from_warehouse_id;
    END IF;

    PERFORM 1 FROM inventory
    WHERE product_id = p_product_id AND warehouse_id = v_first_wh
    FOR UPDATE;

    PERFORM 1 FROM inventory
    WHERE product_id = p_product_id AND warehouse_id = v_second_wh
    FOR UPDATE;

    -- Check destination availability AFTER locking
    SELECT quantity_on_hand - quantity_reserved INTO v_available
    FROM inventory
    WHERE product_id = p_product_id AND warehouse_id = p_to_warehouse_id;

    IF v_available IS NULL OR v_available < v_qty THEN
        RAISE EXCEPTION 'Insufficient unreserved stock at destination warehouse %',
            p_to_warehouse_id;
    END IF;

    -- Release reserved quantity at source
    UPDATE inventory
    SET quantity_reserved = quantity_reserved - v_qty,
        last_updated = NOW()
    WHERE product_id = p_product_id AND warehouse_id = p_from_warehouse_id;

    -- Reserve at destination
    UPDATE inventory
    SET quantity_reserved = quantity_reserved + v_qty,
        last_updated = NOW()
    WHERE product_id = p_product_id AND warehouse_id = p_to_warehouse_id;

    -- Update reservation record to point to new warehouse
    UPDATE reservations
    SET warehouse_id = p_to_warehouse_id
    WHERE reservation_id = v_res_id;

    -- Audit trail
    INSERT INTO stock_movements (product_id, warehouse_id, movement_type, quantity, reference_id)
    VALUES (p_product_id, p_from_warehouse_id, 'RELEASE', v_qty, p_order_id);

    INSERT INTO stock_movements (product_id, warehouse_id, movement_type, quantity, reference_id)
    VALUES (p_product_id, p_to_warehouse_id, 'RESERVATION', v_qty, p_order_id);

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;


---------------------------------------------------------------------
-- batch_reserve_orders: Reserve multiple orders in a single call
-- FIXES:
--   1. Phase 1: Collect ALL (product_id, warehouse_id) pairs across
--      ALL orders in the batch, lock them in deterministic order
--      upfront to prevent deadlocks between concurrent batch calls.
--   2. Phase 2: Lock each order row FOR UPDATE before processing
--      to serialize with concurrent cancel/fulfill/reallocate.
--   3. Use BEGIN...EXCEPTION for per-order savepoint isolation so
--      a failed order's changes are rolled back without affecting
--      successful orders.
--   4. Mark failed orders as FAILED (not left PENDING).
--   5. Cumulative availability is naturally tracked: earlier orders'
--      inventory changes are visible to later orders within the
--      same transaction.
---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION batch_reserve_orders(p_order_ids INT[])
RETURNS TABLE(order_id INT, success BOOLEAN, error_msg TEXT) AS $$
DECLARE
    v_oid INT;
    v_line RECORD;
    v_inv RECORD;
    v_available INT;
    v_status VARCHAR;
BEGIN
    -- Phase 1: Lock ALL inventory rows needed by ANY order in the batch
    -- in deterministic (product_id, warehouse_id) order.
    FOR v_inv IN
        SELECT DISTINCT ol.product_id, ol.warehouse_id
        FROM unnest(p_order_ids) AS u(oid)
        JOIN order_lines ol ON ol.order_id = u.oid
        ORDER BY ol.product_id, ol.warehouse_id
    LOOP
        PERFORM 1 FROM inventory
        WHERE inventory.product_id = v_inv.product_id
          AND inventory.warehouse_id = v_inv.warehouse_id
        FOR UPDATE;
    END LOOP;

    -- Phase 2: Process each order with savepoint-based isolation.
    FOREACH v_oid IN ARRAY p_order_ids LOOP
        -- Lock the order row to serialize with concurrent operations.
        SELECT o.status INTO v_status
        FROM orders o
        WHERE o.order_id = v_oid
        FOR UPDATE;

        IF v_status IS NULL THEN
            order_id := v_oid;
            success := FALSE;
            error_msg := format('Order %s not found', v_oid);
            RETURN NEXT;
            CONTINUE;
        END IF;

        IF v_status != 'PENDING' THEN
            order_id := v_oid;
            success := FALSE;
            error_msg := format('Order %s is not in PENDING status (current: %s)', v_oid, v_status);
            RETURN NEXT;
            CONTINUE;
        END IF;

        BEGIN
            FOR v_line IN
                SELECT ol.line_id, ol.product_id, ol.warehouse_id, ol.quantity
                FROM order_lines ol
                WHERE ol.order_id = v_oid
                ORDER BY ol.product_id, ol.warehouse_id
            LOOP
                -- Rows already locked in Phase 1; read current values
                SELECT i.quantity_on_hand - i.quantity_reserved
                INTO v_available
                FROM inventory i
                WHERE i.product_id = v_line.product_id
                  AND i.warehouse_id = v_line.warehouse_id;

                IF v_available IS NULL OR v_available < v_line.quantity THEN
                    RAISE EXCEPTION 'Insufficient stock for product % in warehouse %: available=%, requested=%',
                        v_line.product_id, v_line.warehouse_id,
                        COALESCE(v_available, 0), v_line.quantity;
                END IF;

                UPDATE inventory
                SET quantity_reserved = quantity_reserved + v_line.quantity,
                    last_updated = NOW()
                WHERE product_id = v_line.product_id
                  AND warehouse_id = v_line.warehouse_id;

                INSERT INTO reservations (order_id, product_id, warehouse_id, quantity, status)
                VALUES (v_oid, v_line.product_id, v_line.warehouse_id, v_line.quantity, 'ACTIVE');

                INSERT INTO stock_movements (product_id, warehouse_id, movement_type, quantity, reference_id)
                VALUES (v_line.product_id, v_line.warehouse_id, 'RESERVATION', v_line.quantity, v_oid);
            END LOOP;

            UPDATE orders SET status = 'RESERVED', processed_at = NOW()
            WHERE orders.order_id = v_oid;

            order_id := v_oid;
            success := TRUE;
            error_msg := NULL;
            RETURN NEXT;

        EXCEPTION WHEN OTHERS THEN
            -- Savepoint automatically rolled back; mark order as FAILED
            UPDATE orders SET status = 'FAILED', processed_at = NOW()
            WHERE orders.order_id = v_oid;

            order_id := v_oid;
            success := FALSE;
            error_msg := SQLERRM;
            RETURN NEXT;
        END;
    END LOOP;
END;
$$ LANGUAGE plpgsql;
