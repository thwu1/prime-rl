
-- Stored procedures for inventory reservation system
-- These procedures have concurrency defects that must be fixed.

---------------------------------------------------------------------
-- reserve_order_stock: Reserve inventory for all lines in an order
---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION reserve_order_stock(p_order_id INT)
RETURNS BOOLEAN AS $$
DECLARE
    v_line RECORD;
    v_available INT;
BEGIN
    -- Verify order is pending
    IF NOT EXISTS (
        SELECT 1 FROM orders WHERE order_id = p_order_id AND status = 'PENDING'
    ) THEN
        RAISE EXCEPTION 'Order % is not in PENDING status', p_order_id;
    END IF;

    -- Iterate through order lines and reserve stock
    FOR v_line IN
        SELECT ol.line_id, ol.product_id, ol.warehouse_id, ol.quantity
        FROM order_lines ol
        WHERE ol.order_id = p_order_id
    LOOP
        -- Lock the inventory row and check availability
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

        -- Reserve the stock
        UPDATE inventory
        SET quantity_reserved = quantity_reserved + v_line.quantity,
            last_updated = NOW()
        WHERE product_id = v_line.product_id
          AND warehouse_id = v_line.warehouse_id;

        -- Record the reservation
        INSERT INTO reservations (order_id, product_id, warehouse_id, quantity, status)
        VALUES (p_order_id, v_line.product_id, v_line.warehouse_id, v_line.quantity, 'ACTIVE');

        -- Audit trail
        INSERT INTO stock_movements (product_id, warehouse_id, movement_type, quantity, reference_id)
        VALUES (v_line.product_id, v_line.warehouse_id, 'RESERVATION', v_line.quantity, p_order_id);
    END LOOP;

    -- Mark order as reserved
    UPDATE orders SET status = 'RESERVED', processed_at = NOW()
    WHERE order_id = p_order_id;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;


---------------------------------------------------------------------
-- cancel_order: Cancel a reserved order and release stock
---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION cancel_order(p_order_id INT)
RETURNS BOOLEAN AS $$
DECLARE
    v_status VARCHAR;
    v_res RECORD;
BEGIN
    -- Check current order status
    SELECT status INTO v_status
    FROM orders
    WHERE order_id = p_order_id;

    IF v_status IS NULL THEN
        RAISE EXCEPTION 'Order % not found', p_order_id;
    END IF;

    IF v_status != 'RESERVED' THEN
        RAISE EXCEPTION 'Order % is not in RESERVED status (current: %)',
            p_order_id, v_status;
    END IF;

    -- Release each active reservation
    FOR v_res IN
        SELECT reservation_id, product_id, warehouse_id, quantity
        FROM reservations
        WHERE order_id = p_order_id AND status = 'ACTIVE'
    LOOP
        -- Decrease reserved quantity
        UPDATE inventory
        SET quantity_reserved = quantity_reserved - v_res.quantity,
            last_updated = NOW()
        WHERE product_id = v_res.product_id
          AND warehouse_id = v_res.warehouse_id;

        -- Audit trail
        INSERT INTO stock_movements (product_id, warehouse_id, movement_type, quantity, reference_id)
        VALUES (v_res.product_id, v_res.warehouse_id, 'RELEASE', v_res.quantity, p_order_id);
    END LOOP;

    -- Mark order as cancelled
    UPDATE orders SET status = 'CANCELLED', processed_at = NOW()
    WHERE order_id = p_order_id;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;


---------------------------------------------------------------------
-- fulfill_order: Ship a reserved order, deducting on-hand stock
---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fulfill_order(p_order_id INT)
RETURNS BOOLEAN AS $$
DECLARE
    v_status VARCHAR;
    v_res RECORD;
BEGIN
    -- Check current order status
    SELECT status INTO v_status
    FROM orders
    WHERE order_id = p_order_id;

    IF v_status IS NULL THEN
        RAISE EXCEPTION 'Order % not found', p_order_id;
    END IF;

    IF v_status != 'RESERVED' THEN
        RAISE EXCEPTION 'Order % is not in RESERVED status (current: %)',
            p_order_id, v_status;
    END IF;

    -- Process each active reservation
    FOR v_res IN
        SELECT reservation_id, product_id, warehouse_id, quantity
        FROM reservations
        WHERE order_id = p_order_id AND status = 'ACTIVE'
    LOOP
        -- Deduct from on-hand and release reservation
        UPDATE inventory
        SET quantity_on_hand = quantity_on_hand - v_res.quantity,
            quantity_reserved = quantity_reserved - v_res.quantity,
            last_updated = NOW()
        WHERE product_id = v_res.product_id
          AND warehouse_id = v_res.warehouse_id;

        -- Audit trail
        INSERT INTO stock_movements (product_id, warehouse_id, movement_type, quantity, reference_id)
        VALUES (v_res.product_id, v_res.warehouse_id, 'SHIPMENT', v_res.quantity, p_order_id);
    END LOOP;

    -- Mark order as shipped
    UPDATE orders SET status = 'SHIPPED', processed_at = NOW()
    WHERE order_id = p_order_id;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;


---------------------------------------------------------------------
-- transfer_stock: Move unreserved stock between warehouses
---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION transfer_stock(
    p_product_id INT,
    p_from_warehouse_id INT,
    p_to_warehouse_id INT,
    p_quantity INT
) RETURNS BOOLEAN AS $$
DECLARE
    v_available INT;
BEGIN
    IF p_quantity <= 0 THEN
        RAISE EXCEPTION 'Transfer quantity must be positive';
    END IF;

    IF p_from_warehouse_id = p_to_warehouse_id THEN
        RAISE EXCEPTION 'Cannot transfer to same warehouse';
    END IF;

    -- Check available stock at source
    SELECT quantity_on_hand - quantity_reserved
    INTO v_available
    FROM inventory
    WHERE product_id = p_product_id
      AND warehouse_id = p_from_warehouse_id;

    IF v_available IS NULL THEN
        RAISE EXCEPTION 'No inventory record for product % in warehouse %',
            p_product_id, p_from_warehouse_id;
    END IF;

    IF v_available < p_quantity THEN
        RAISE EXCEPTION 'Insufficient available stock: available=%, requested=%',
            v_available, p_quantity;
    END IF;

    -- Deduct from source
    UPDATE inventory
    SET quantity_on_hand = quantity_on_hand - p_quantity,
        last_updated = NOW()
    WHERE product_id = p_product_id
      AND warehouse_id = p_from_warehouse_id;

    -- Ensure destination record exists
    INSERT INTO inventory (product_id, warehouse_id, quantity_on_hand, quantity_reserved)
    VALUES (p_product_id, p_to_warehouse_id, 0, 0)
    ON CONFLICT (product_id, warehouse_id) DO NOTHING;

    -- Add to destination
    UPDATE inventory
    SET quantity_on_hand = quantity_on_hand + p_quantity,
        last_updated = NOW()
    WHERE product_id = p_product_id
      AND warehouse_id = p_to_warehouse_id;

    -- Audit trail
    INSERT INTO stock_movements (product_id, warehouse_id, movement_type, quantity, reference_id)
    VALUES (p_product_id, p_from_warehouse_id, 'TRANSFER_OUT', p_quantity, NULL);

    INSERT INTO stock_movements (product_id, warehouse_id, movement_type, quantity, reference_id)
    VALUES (p_product_id, p_to_warehouse_id, 'TRANSFER_IN', p_quantity, NULL);

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;


---------------------------------------------------------------------
-- reallocate_reservation: Move a reservation between warehouses
---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION reallocate_reservation(
    p_order_id INT,
    p_product_id INT,
    p_from_warehouse_id INT,
    p_to_warehouse_id INT
) RETURNS BOOLEAN AS $$
DECLARE
    v_res_id INT;
    v_qty INT;
    v_available INT;
BEGIN
    IF p_from_warehouse_id = p_to_warehouse_id THEN
        RAISE EXCEPTION 'Source and destination warehouses must differ';
    END IF;

    -- Check order is reserved
    IF NOT EXISTS (
        SELECT 1 FROM orders WHERE order_id = p_order_id AND status = 'RESERVED'
    ) THEN
        RAISE EXCEPTION 'Order % is not in RESERVED status', p_order_id;
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

    -- Check destination has enough unreserved capacity
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
---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION batch_reserve_orders(p_order_ids INT[])
RETURNS TABLE(order_id INT, success BOOLEAN, error_msg TEXT) AS $$
DECLARE
    v_oid INT;
    v_line RECORD;
    v_available INT;
BEGIN
    -- Process each order in the array
    FOREACH v_oid IN ARRAY p_order_ids LOOP
        -- Check order status
        IF NOT EXISTS (
            SELECT 1 FROM orders o WHERE o.order_id = v_oid AND o.status = 'PENDING'
        ) THEN
            order_id := v_oid;
            success := FALSE;
            error_msg := format('Order %s is not in PENDING status', v_oid);
            RETURN NEXT;
            CONTINUE;
        END IF;

        BEGIN
            -- Reserve stock for each order line
            FOR v_line IN
                SELECT ol.line_id, ol.product_id, ol.warehouse_id, ol.quantity
                FROM order_lines ol
                WHERE ol.order_id = v_oid
            LOOP
                -- Lock and check availability
                SELECT i.quantity_on_hand - i.quantity_reserved
                INTO v_available
                FROM inventory i
                WHERE i.product_id = v_line.product_id
                  AND i.warehouse_id = v_line.warehouse_id
                FOR UPDATE;

                IF v_available IS NULL OR v_available < v_line.quantity THEN
                    RAISE EXCEPTION 'Insufficient stock for product % in warehouse %',
                        v_line.product_id, v_line.warehouse_id;
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
            -- Failed order stays PENDING (not marked FAILED)
            order_id := v_oid;
            success := FALSE;
            error_msg := SQLERRM;
            RETURN NEXT;
        END;
    END LOOP;
END;
$$ LANGUAGE plpgsql;
