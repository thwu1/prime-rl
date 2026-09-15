"""
Tests for concurrent inventory reservation system.

"""

import pytest
import psycopg2
import threading

DB_NAME = "inventory_test"
DB_USER = "postgres"
DB_HOST = "127.0.0.1"
DB_PORT = 5432


def get_conn(autocommit=True):
    conn = psycopg2.connect(
        dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
    )
    if autocommit:
        conn.autocommit = True
    return conn


@pytest.fixture(autouse=True)
def clean_db():
    """Reset database state between tests."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DROP TRIGGER IF EXISTS trg_test_delay ON inventory")
    cur.execute("DROP FUNCTION IF EXISTS _test_delay_trigger()")
    cur.execute(
        "TRUNCATE stock_movements, reservations, order_lines, orders, "
        "inventory, warehouses, products RESTART IDENTITY CASCADE"
    )
    conn.close()
    yield
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DROP TRIGGER IF EXISTS trg_test_delay ON inventory")
    cur.execute("DROP FUNCTION IF EXISTS _test_delay_trigger()")
    conn.close()


def setup_delay_trigger(delay_sec=0.05):
    """Add a trigger to slow down inventory updates, widening the race window."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "CREATE OR REPLACE FUNCTION _test_delay_trigger() "
        "RETURNS TRIGGER AS $$ "
        "BEGIN PERFORM pg_sleep(%s); RETURN NEW; END; "
        "$$ LANGUAGE plpgsql",
        (delay_sec,),
    )
    cur.execute(
        "DROP TRIGGER IF EXISTS trg_test_delay ON inventory"
    )
    cur.execute(
        "CREATE TRIGGER trg_test_delay BEFORE UPDATE ON inventory "
        "FOR EACH ROW EXECUTE FUNCTION _test_delay_trigger()"
    )
    conn.close()


def seed(num_products=5, num_warehouses=2, stock=10000):
    """Create products, warehouses, and inventory with given stock level."""
    conn = get_conn()
    cur = conn.cursor()
    for wid in range(1, num_warehouses + 1):
        cur.execute(
            "INSERT INTO warehouses (warehouse_id, code, name) VALUES (%s, %s, %s)",
            (wid, f"W{wid}", f"Warehouse {wid}"),
        )
    for pid in range(1, num_products + 1):
        cur.execute(
            "INSERT INTO products (product_id, sku, name, category, unit_cost) "
            "VALUES (%s, %s, %s, 'GEN', 10.00)",
            (pid, f"SKU{pid:04d}", f"Product {pid}"),
        )
        for wid in range(1, num_warehouses + 1):
            cur.execute(
                "INSERT INTO inventory (product_id, warehouse_id, quantity_on_hand) "
                "VALUES (%s, %s, %s)",
                (pid, wid, stock),
            )
    conn.close()


def make_order(oid, product_ids, wh=1, qty=1):
    """Create an order with lines for the given product list (order of IDs preserved)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO orders (order_id, order_number, customer_id) VALUES (%s, %s, 1)",
        (oid, f"ORD-{oid:06d}"),
    )
    for pid in product_ids:
        cur.execute(
            "INSERT INTO order_lines (order_id, product_id, warehouse_id, quantity, unit_price) "
            "VALUES (%s, %s, %s, %s, 10.00)",
            (oid, pid, wh, qty),
        )
    conn.close()


# ---------- reserve_order_stock tests ----------


def test_basic_reservation():
    """Reservation succeeds, updates order status, creates reservation records."""
    seed(3, 1)
    make_order(1, [1, 2, 3], qty=5)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT reserve_order_stock(1)")
    assert cur.fetchone()[0] is True

    cur.execute("SELECT status FROM orders WHERE order_id = 1")
    assert cur.fetchone()[0] == "RESERVED"

    cur.execute(
        "SELECT SUM(quantity_reserved) FROM inventory WHERE warehouse_id = 1"
    )
    assert cur.fetchone()[0] == 15  # 5 * 3

    cur.execute(
        "SELECT COUNT(*) FROM reservations WHERE order_id = 1 AND status = 'ACTIVE'"
    )
    assert cur.fetchone()[0] == 3
    conn.close()


def test_reservation_no_deadlock():
    """Concurrent reservations with overlapping products in reverse order must not deadlock."""
    seed(5, 1, stock=500000)
    setup_delay_trigger(0.05)

    deadlocks = 0
    NUM_TRIALS = 25

    for trial in range(NUM_TRIALS):
        o1 = trial * 2 + 1
        o2 = trial * 2 + 2
        make_order(o1, [1, 2, 3, 4, 5], qty=1)
        make_order(o2, [5, 4, 3, 2, 1], qty=1)  # reversed product order

        errs = [None, None]
        barrier = threading.Barrier(2, timeout=15)

        def do_reserve(oid, idx):
            try:
                c = psycopg2.connect(
                    dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
                )
                c.autocommit = True
                barrier.wait()
                cur = c.cursor()
                cur.execute("SELECT reserve_order_stock(%s)", (oid,))
                c.close()
            except Exception as e:
                errs[idx] = str(e)
                try:
                    c.close()
                except Exception:
                    pass

        t1 = threading.Thread(target=do_reserve, args=(o1, 0))
        t2 = threading.Thread(target=do_reserve, args=(o2, 1))
        t1.start()
        t2.start()
        t1.join(20)
        t2.join(20)

        for e in errs:
            if e and "deadlock" in e.lower():
                deadlocks += 1

    assert deadlocks == 0, (
        f"Deadlock detected in {deadlocks} out of {NUM_TRIALS} concurrent reservation trials"
    )


# ---------- cancel_order tests ----------


def test_cancel_releases_reservations():
    """Cancel must mark all reservations as RELEASED and restore inventory."""
    seed(3, 1, stock=100)
    make_order(1, [1, 2, 3], qty=5)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT reserve_order_stock(1)")
    assert cur.fetchone()[0] is True

    cur.execute("SELECT cancel_order(1)")
    assert cur.fetchone()[0] is True

    # All reservations must be RELEASED, none ACTIVE
    cur.execute(
        "SELECT COUNT(*) FROM reservations WHERE order_id = 1 AND status = 'ACTIVE'"
    )
    active = cur.fetchone()[0]
    assert active == 0, f"Expected 0 active reservations after cancel, got {active}"

    cur.execute(
        "SELECT COUNT(*) FROM reservations WHERE order_id = 1 AND status = 'RELEASED'"
    )
    released = cur.fetchone()[0]
    assert released == 3, f"Expected 3 released reservations, got {released}"

    # Inventory fully released
    cur.execute(
        "SELECT SUM(quantity_reserved) FROM inventory WHERE warehouse_id = 1"
    )
    assert cur.fetchone()[0] == 0, "Reserved quantity not fully released after cancel"
    conn.close()


def test_cancel_sets_order_status():
    """Cancel must set order status to CANCELLED."""
    seed(2, 1)
    make_order(1, [1, 2], qty=3)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT reserve_order_stock(1)")
    cur.execute("SELECT cancel_order(1)")
    cur.execute("SELECT status FROM orders WHERE order_id = 1")
    assert cur.fetchone()[0] == "CANCELLED"
    conn.close()


def test_double_cancel_no_corruption():
    """Cancelling an already-cancelled order must not corrupt inventory data."""
    seed(3, 1, stock=200)
    make_order(1, [1, 2, 3], qty=10)

    conn = get_conn()
    cur = conn.cursor()

    # Reserve and cancel
    cur.execute("SELECT reserve_order_stock(1)")
    cur.execute("SELECT cancel_order(1)")

    # Snapshot
    cur.execute(
        "SELECT product_id, quantity_on_hand, quantity_reserved "
        "FROM inventory WHERE warehouse_id = 1 ORDER BY product_id"
    )
    snapshot = cur.fetchall()

    # Second cancel attempt
    try:
        cur.execute("SELECT cancel_order(1)")
    except psycopg2.Error:
        conn.rollback()

    # Verify no corruption
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "SELECT product_id, quantity_on_hand, quantity_reserved "
        "FROM inventory WHERE warehouse_id = 1 ORDER BY product_id"
    )
    after = cur.fetchall()
    assert snapshot == after, (
        f"Double cancel corrupted inventory: before={snapshot}, after={after}"
    )

    cur.execute("SELECT COUNT(*) FROM inventory WHERE quantity_reserved < 0")
    assert cur.fetchone()[0] == 0, "Negative quantity_reserved after double cancel"
    conn.close()


# ---------- transfer_stock tests ----------


def test_basic_transfer():
    """Transfer moves stock correctly between warehouses."""
    seed(1, 2, stock=100)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT transfer_stock(1, 1, 2, 30)")
    assert cur.fetchone()[0] is True

    cur.execute(
        "SELECT quantity_on_hand FROM inventory WHERE product_id = 1 AND warehouse_id = 1"
    )
    assert cur.fetchone()[0] == 70

    cur.execute(
        "SELECT quantity_on_hand FROM inventory WHERE product_id = 1 AND warehouse_id = 2"
    )
    assert cur.fetchone()[0] == 130
    conn.close()


def test_transfer_no_deadlock():
    """Opposing concurrent transfers (W1->W2, W2->W1) must not deadlock."""
    seed(1, 2, stock=500000)
    setup_delay_trigger(0.05)

    deadlocks = 0
    NUM_TRIALS = 25

    for trial in range(NUM_TRIALS):
        errs = [None, None]
        barrier = threading.Barrier(2, timeout=15)

        def do_transfer(fw, tw, idx):
            try:
                c = psycopg2.connect(
                    dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
                )
                c.autocommit = True
                barrier.wait()
                cur = c.cursor()
                cur.execute(
                    "SELECT transfer_stock(1, %s, %s, 10)", (fw, tw)
                )
                c.close()
            except Exception as e:
                errs[idx] = str(e)
                try:
                    c.close()
                except Exception:
                    pass

        t1 = threading.Thread(target=do_transfer, args=(1, 2, 0))
        t2 = threading.Thread(target=do_transfer, args=(2, 1, 1))
        t1.start()
        t2.start()
        t1.join(20)
        t2.join(20)

        for e in errs:
            if e and "deadlock" in e.lower():
                deadlocks += 1

    assert deadlocks == 0, (
        f"Deadlock detected in {deadlocks} out of {NUM_TRIALS} concurrent transfer trials"
    )


def test_transfer_conserves_stock():
    """Total stock across warehouses must be conserved after concurrent transfers."""
    seed(1, 2, stock=5000)

    errors = []
    threads = []

    def do_transfer(fw, tw, qty):
        try:
            c = psycopg2.connect(
                dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
            )
            c.autocommit = True
            cur = c.cursor()
            cur.execute("SELECT transfer_stock(1, %s, %s, %s)", (fw, tw, qty))
            c.close()
        except Exception as e:
            errors.append(str(e))
            try:
                c.close()
            except Exception:
                pass

    for _ in range(20):
        t1 = threading.Thread(target=do_transfer, args=(1, 2, 10))
        t2 = threading.Thread(target=do_transfer, args=(2, 1, 10))
        threads.extend([t1, t2])
        t1.start()
        t2.start()

    for t in threads:
        t.join(30)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT SUM(quantity_on_hand) FROM inventory WHERE product_id = 1")
    total = cur.fetchone()[0]
    assert total == 10000, f"Stock not conserved: expected 10000, got {total}"

    cur.execute("SELECT COUNT(*) FROM inventory WHERE quantity_on_hand < 0")
    assert cur.fetchone()[0] == 0, "Negative quantity_on_hand after transfers"
    conn.close()


def test_transfer_respects_reserved():
    """Transfer must not move stock that is reserved."""
    seed(1, 2, stock=100)
    make_order(1, [1], wh=1, qty=80)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT reserve_order_stock(1)")

    # Available = 100 - 80 = 20; attempt to transfer 50
    transfer_succeeded = False
    try:
        cur.execute("SELECT transfer_stock(1, 1, 2, 50)")
        transfer_succeeded = cur.fetchone()[0] is True
    except psycopg2.Error:
        conn.rollback()
        conn.autocommit = True
        cur = conn.cursor()

    if transfer_succeeded:
        # If the transfer went through, on_hand must still be >= reserved
        cur.execute(
            "SELECT quantity_on_hand, quantity_reserved "
            "FROM inventory WHERE product_id = 1 AND warehouse_id = 1"
        )
        oh, res = cur.fetchone()
        assert oh >= res, (
            f"Transfer violated reserve constraint: on_hand={oh}, reserved={res}"
        )
    # If exception was raised, that is the correct behavior (transfer refused)
    conn.close()


# ---------- fulfill_order tests ----------


def test_basic_fulfillment():
    """Fulfillment succeeds, sets order status to SHIPPED."""
    seed(3, 1, stock=100)
    make_order(1, [1, 2, 3], qty=5)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT reserve_order_stock(1)")
    assert cur.fetchone()[0] is True

    cur.execute("SELECT fulfill_order(1)")
    assert cur.fetchone()[0] is True

    cur.execute("SELECT status FROM orders WHERE order_id = 1")
    assert cur.fetchone()[0] == "SHIPPED"
    conn.close()


def test_fulfill_updates_inventory():
    """Fulfillment must decrement both quantity_on_hand and quantity_reserved."""
    seed(3, 1, stock=100)
    make_order(1, [1, 2, 3], qty=5)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT reserve_order_stock(1)")
    cur.execute("SELECT fulfill_order(1)")

    for pid in [1, 2, 3]:
        cur.execute(
            "SELECT quantity_on_hand, quantity_reserved "
            "FROM inventory WHERE product_id = %s AND warehouse_id = 1",
            (pid,)
        )
        oh, res = cur.fetchone()
        assert oh == 95, f"Product {pid}: expected on_hand 95, got {oh}"
        assert res == 0, f"Product {pid}: expected reserved 0, got {res}"

    conn.close()


def test_fulfill_marks_reservations_fulfilled():
    """Fulfillment must mark all reservations as FULFILLED."""
    seed(3, 1, stock=100)
    make_order(1, [1, 2, 3], qty=5)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT reserve_order_stock(1)")
    cur.execute("SELECT fulfill_order(1)")

    cur.execute(
        "SELECT COUNT(*) FROM reservations WHERE order_id = 1 AND status = 'FULFILLED'"
    )
    fulfilled = cur.fetchone()[0]
    assert fulfilled == 3, f"Expected 3 fulfilled reservations, got {fulfilled}"

    cur.execute(
        "SELECT COUNT(*) FROM reservations WHERE order_id = 1 AND status = 'ACTIVE'"
    )
    active = cur.fetchone()[0]
    assert active == 0, f"Expected 0 active reservations after fulfill, got {active}"
    conn.close()


def test_fulfill_no_deadlock():
    """Concurrent fulfillments with overlapping inventory rows must not deadlock."""
    seed(5, 1, stock=500000)
    setup_delay_trigger(0.05)

    deadlocks = 0
    NUM_TRIALS = 20

    for trial in range(NUM_TRIALS):
        o1 = trial * 2 + 1
        o2 = trial * 2 + 2

        conn = get_conn()
        cur = conn.cursor()

        # Create RESERVED orders directly
        cur.execute(
            "INSERT INTO orders (order_id, order_number, customer_id, status, processed_at) "
            "VALUES (%s, %s, 1, 'RESERVED', NOW())",
            (o1, f"ORD-{o1:06d}")
        )
        cur.execute(
            "INSERT INTO orders (order_id, order_number, customer_id, status, processed_at) "
            "VALUES (%s, %s, 1, 'RESERVED', NOW())",
            (o2, f"ORD-{o2:06d}")
        )

        # Create order lines for completeness
        for pid in [1, 2, 3, 4, 5]:
            cur.execute(
                "INSERT INTO order_lines (order_id, product_id, warehouse_id, quantity, unit_price) "
                "VALUES (%s, %s, 1, 1, 10.00)",
                (o1, pid)
            )
            cur.execute(
                "INSERT INTO order_lines (order_id, product_id, warehouse_id, quantity, unit_price) "
                "VALUES (%s, %s, 1, 1, 10.00)",
                (o2, pid)
            )

        # Insert reservations for order 1 in ASCENDING product order
        for pid in [1, 2, 3, 4, 5]:
            cur.execute(
                "INSERT INTO reservations (order_id, product_id, warehouse_id, quantity, status) "
                "VALUES (%s, %s, 1, 1, 'ACTIVE')",
                (o1, pid)
            )

        # Insert reservations for order 2 in DESCENDING product order
        # This creates different natural iteration order without ORDER BY
        for pid in [5, 4, 3, 2, 1]:
            cur.execute(
                "INSERT INTO reservations (order_id, product_id, warehouse_id, quantity, status) "
                "VALUES (%s, %s, 1, 1, 'ACTIVE')",
                (o2, pid)
            )

        # Update inventory to reflect both orders' reservations
        for pid in [1, 2, 3, 4, 5]:
            cur.execute(
                "UPDATE inventory SET quantity_reserved = quantity_reserved + 2 "
                "WHERE product_id = %s AND warehouse_id = 1",
                (pid,)
            )

        conn.close()

        errs = [None, None]
        barrier = threading.Barrier(2, timeout=15)

        def do_fulfill(oid, idx):
            try:
                c = psycopg2.connect(
                    dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
                )
                c.autocommit = True
                barrier.wait()
                cur = c.cursor()
                cur.execute("SELECT fulfill_order(%s)", (oid,))
                c.close()
            except Exception as e:
                errs[idx] = str(e)
                try:
                    c.close()
                except Exception:
                    pass

        t1 = threading.Thread(target=do_fulfill, args=(o1, 0))
        t2 = threading.Thread(target=do_fulfill, args=(o2, 1))
        t1.start()
        t2.start()
        t1.join(20)
        t2.join(20)

        for e in errs:
            if e and "deadlock" in e.lower():
                deadlocks += 1

    assert deadlocks == 0, (
        f"Deadlock detected in {deadlocks} out of {NUM_TRIALS} concurrent fulfillment trials"
    )


# ---------- cross-procedure interaction tests ----------


def test_concurrent_cancel_fulfill_no_corruption():
    """Cancel and fulfill racing on the same order must not produce constraint violations."""
    seed(3, 1, stock=500000)
    setup_delay_trigger(0.03)

    NUM_TRIALS = 20
    constraint_violations = 0

    for trial in range(NUM_TRIALS):
        oid = trial + 1
        make_order(oid, [1, 2, 3], wh=1, qty=10)

        # Reserve the order first
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT reserve_order_stock(%s)", (oid,))
        conn.close()

        errors = [None, None]
        barrier = threading.Barrier(2, timeout=15)

        def do_cancel(idx):
            try:
                c = psycopg2.connect(
                    dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
                )
                c.autocommit = True
                barrier.wait()
                cur = c.cursor()
                cur.execute("SELECT cancel_order(%s)", (oid,))
                c.close()
            except Exception as e:
                errors[idx] = str(e)
                try:
                    c.close()
                except Exception:
                    pass

        def do_fulfill(idx):
            try:
                c = psycopg2.connect(
                    dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
                )
                c.autocommit = True
                barrier.wait()
                cur = c.cursor()
                cur.execute("SELECT fulfill_order(%s)", (oid,))
                c.close()
            except Exception as e:
                errors[idx] = str(e)
                try:
                    c.close()
                except Exception:
                    pass

        t1 = threading.Thread(target=do_cancel, args=(0,))
        t2 = threading.Thread(target=do_fulfill, args=(1,))
        t1.start()
        t2.start()
        t1.join(20)
        t2.join(20)

        for e in errors:
            if e and ("violates" in e.lower() or "check constraint" in e.lower()):
                constraint_violations += 1

    # With proper locking, the loser gets a clean status-based rejection,
    # never a constraint violation from double-processing
    assert constraint_violations == 0, (
        f"Got {constraint_violations} constraint violations in {NUM_TRIALS} trials; "
        "concurrent cancel/fulfill should produce clean status rejections, not constraint errors"
    )

    # Verify final state: all orders must be in a terminal state
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM orders WHERE order_id <= %s AND status NOT IN ('CANCELLED', 'SHIPPED')",
        (NUM_TRIALS,)
    )
    stuck = cur.fetchone()[0]
    assert stuck == 0, f"{stuck} orders not in terminal state after cancel/fulfill race"

    # No inventory constraint violations
    cur.execute(
        "SELECT COUNT(*) FROM inventory "
        "WHERE quantity_reserved < 0 OR quantity_on_hand < 0 OR quantity_reserved > quantity_on_hand"
    )
    assert cur.fetchone()[0] == 0, "Inventory constraint violation after cancel/fulfill race"
    conn.close()


def test_reservation_quantity_invariant():
    """quantity_reserved must equal the sum of ACTIVE reservation quantities after mixed operations."""
    seed(5, 2, stock=1000)

    # Create and reserve several orders across warehouses
    for oid in range(1, 6):
        products = [(oid % 5) + 1, ((oid + 1) % 5) + 1]
        wh = (oid % 2) + 1
        make_order(oid, products, wh=wh, qty=10)

    conn = get_conn()
    cur = conn.cursor()
    for oid in range(1, 6):
        cur.execute("SELECT reserve_order_stock(%s)", (oid,))

    # Cancel some orders
    cur.execute("SELECT cancel_order(1)")
    cur.execute("SELECT cancel_order(3)")

    # Fulfill some orders
    cur.execute("SELECT fulfill_order(2)")
    cur.execute("SELECT fulfill_order(4)")

    # Order 5 remains RESERVED

    # Check that quantity_reserved matches the sum of ACTIVE reservation quantities
    cur.execute("""
        SELECT i.product_id, i.warehouse_id, i.quantity_reserved,
               COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0) AS active_sum
        FROM inventory i
        LEFT JOIN reservations r
            ON i.product_id = r.product_id AND i.warehouse_id = r.warehouse_id
        GROUP BY i.product_id, i.warehouse_id, i.quantity_reserved
        HAVING i.quantity_reserved != COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0)
    """)
    mismatches = cur.fetchall()
    assert len(mismatches) == 0, (
        f"quantity_reserved does not match active reservations: {mismatches}"
    )

    # Verify cancelled orders have all RELEASED reservations
    cur.execute(
        "SELECT COUNT(*) FROM reservations WHERE order_id IN (1, 3) AND status = 'ACTIVE'"
    )
    assert cur.fetchone()[0] == 0, "Cancelled orders still have ACTIVE reservations"

    # Verify fulfilled orders have all FULFILLED reservations
    cur.execute(
        "SELECT COUNT(*) FROM reservations WHERE order_id IN (2, 4) AND status = 'ACTIVE'"
    )
    assert cur.fetchone()[0] == 0, "Fulfilled orders still have ACTIVE reservations"

    cur.execute(
        "SELECT COUNT(*) FROM reservations WHERE order_id IN (2, 4) AND status = 'FULFILLED'"
    )
    fulfilled = cur.fetchone()[0]
    assert fulfilled > 0, "No FULFILLED reservations found for fulfilled orders"

    conn.close()


# ---------- reallocate_reservation tests ----------


def test_basic_reallocation():
    """Reallocation moves reserved quantity from one warehouse to another."""
    seed(3, 2, stock=100)
    make_order(1, [1, 2, 3], wh=1, qty=5)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT reserve_order_stock(1)")
    assert cur.fetchone()[0] is True

    # Reallocate product 1's reservation from W1 to W2
    cur.execute("SELECT reallocate_reservation(1, 1, 1, 2)")
    assert cur.fetchone()[0] is True

    # Source warehouse reserved should decrease by 5
    cur.execute(
        "SELECT quantity_reserved FROM inventory "
        "WHERE product_id = 1 AND warehouse_id = 1"
    )
    assert cur.fetchone()[0] == 0, "Source warehouse should have 0 reserved after reallocation"

    # Destination warehouse reserved should increase by 5
    cur.execute(
        "SELECT quantity_reserved FROM inventory "
        "WHERE product_id = 1 AND warehouse_id = 2"
    )
    assert cur.fetchone()[0] == 5, "Destination warehouse should have 5 reserved after reallocation"

    # on_hand should be unchanged at both warehouses (reallocation does not move physical stock)
    cur.execute(
        "SELECT quantity_on_hand FROM inventory "
        "WHERE product_id = 1 AND warehouse_id = 1"
    )
    assert cur.fetchone()[0] == 100

    cur.execute(
        "SELECT quantity_on_hand FROM inventory "
        "WHERE product_id = 1 AND warehouse_id = 2"
    )
    assert cur.fetchone()[0] == 100

    # Other products' reservations should be unaffected
    for pid in [2, 3]:
        cur.execute(
            "SELECT quantity_reserved FROM inventory "
            "WHERE product_id = %s AND warehouse_id = 1", (pid,)
        )
        assert cur.fetchone()[0] == 5, f"Product {pid} reservation should be unaffected"

    conn.close()


def test_reallocation_updates_reservation_record():
    """After reallocation, the reservation record's warehouse_id must point to the new warehouse."""
    seed(2, 2, stock=100)
    make_order(1, [1], wh=1, qty=10)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT reserve_order_stock(1)")
    cur.execute("SELECT reallocate_reservation(1, 1, 1, 2)")

    # Reservation record should now point to warehouse 2
    cur.execute(
        "SELECT warehouse_id FROM reservations "
        "WHERE order_id = 1 AND product_id = 1 AND status = 'ACTIVE'"
    )
    wh = cur.fetchone()[0]
    assert wh == 2, (
        f"Reservation should point to warehouse 2 after reallocation, got warehouse {wh}"
    )

    # Verify quantity_reserved invariant holds
    cur.execute("""
        SELECT i.product_id, i.warehouse_id, i.quantity_reserved,
               COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0) AS active_sum
        FROM inventory i
        LEFT JOIN reservations r
            ON i.product_id = r.product_id AND i.warehouse_id = r.warehouse_id
        GROUP BY i.product_id, i.warehouse_id, i.quantity_reserved
        HAVING i.quantity_reserved != COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0)
    """)
    mismatches = cur.fetchall()
    assert len(mismatches) == 0, (
        f"quantity_reserved mismatch after reallocation: {mismatches}"
    )

    conn.close()


def test_reallocate_then_cancel_releases_correctly():
    """Cancel after reallocation must release from the correct (new) warehouse."""
    seed(2, 2, stock=100)
    make_order(1, [1, 2], wh=1, qty=10)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT reserve_order_stock(1)")

    # Reallocate product 1 from W1 to W2
    cur.execute("SELECT reallocate_reservation(1, 1, 1, 2)")

    # Now cancel the entire order
    cur.execute("SELECT cancel_order(1)")
    assert cur.fetchone()[0] is True

    # Product 1 was reallocated to W2, so cancel should release from W2
    # W1: product 1 reserved should be 0 (was reallocated away)
    cur.execute(
        "SELECT quantity_reserved FROM inventory "
        "WHERE product_id = 1 AND warehouse_id = 1"
    )
    assert cur.fetchone()[0] == 0, "W1 product 1 reserved should be 0"

    # W2: product 1 reserved should be 0 (released by cancel from the correct warehouse)
    cur.execute(
        "SELECT quantity_reserved FROM inventory "
        "WHERE product_id = 1 AND warehouse_id = 2"
    )
    assert cur.fetchone()[0] == 0, "W2 product 1 reserved should be 0 after cancel"

    # Product 2 was never reallocated, cancel releases from W1
    cur.execute(
        "SELECT quantity_reserved FROM inventory "
        "WHERE product_id = 2 AND warehouse_id = 1"
    )
    assert cur.fetchone()[0] == 0, "W1 product 2 reserved should be 0 after cancel"

    # All reservations should be RELEASED
    cur.execute(
        "SELECT COUNT(*) FROM reservations WHERE order_id = 1 AND status = 'ACTIVE'"
    )
    assert cur.fetchone()[0] == 0, "Should have no ACTIVE reservations after cancel"

    # Global invariant: quantity_reserved equals sum of ACTIVE reservation quantities
    cur.execute("""
        SELECT i.product_id, i.warehouse_id, i.quantity_reserved,
               COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0) AS active_sum
        FROM inventory i
        LEFT JOIN reservations r
            ON i.product_id = r.product_id AND i.warehouse_id = r.warehouse_id
        GROUP BY i.product_id, i.warehouse_id, i.quantity_reserved
        HAVING i.quantity_reserved != COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0)
    """)
    mismatches = cur.fetchall()
    assert len(mismatches) == 0, (
        f"quantity_reserved mismatch after reallocate+cancel: {mismatches}"
    )

    conn.close()


def test_reallocate_then_fulfill_ships_from_correct_warehouse():
    """Fulfill after reallocation must ship from the correct (new) warehouse."""
    seed(1, 2, stock=100)
    make_order(1, [1], wh=1, qty=10)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT reserve_order_stock(1)")

    # Reallocate from W1 to W2
    cur.execute("SELECT reallocate_reservation(1, 1, 1, 2)")

    # Fulfill the order
    cur.execute("SELECT fulfill_order(1)")
    assert cur.fetchone()[0] is True

    # W1: on_hand should be unchanged (100), reserved should be 0
    cur.execute(
        "SELECT quantity_on_hand, quantity_reserved FROM inventory "
        "WHERE product_id = 1 AND warehouse_id = 1"
    )
    oh, res = cur.fetchone()
    assert oh == 100, f"W1 on_hand should be 100 (untouched by fulfill), got {oh}"
    assert res == 0, f"W1 reserved should be 0, got {res}"

    # W2: on_hand should be 90 (100 - 10 shipped), reserved should be 0
    cur.execute(
        "SELECT quantity_on_hand, quantity_reserved FROM inventory "
        "WHERE product_id = 1 AND warehouse_id = 2"
    )
    oh, res = cur.fetchone()
    assert oh == 90, f"W2 on_hand should be 90 (100 - 10 shipped), got {oh}"
    assert res == 0, f"W2 reserved should be 0 after fulfill, got {res}"

    # Order should be SHIPPED
    cur.execute("SELECT status FROM orders WHERE order_id = 1")
    assert cur.fetchone()[0] == "SHIPPED"

    # Reservation should be FULFILLED
    cur.execute(
        "SELECT COUNT(*) FROM reservations WHERE order_id = 1 AND status = 'FULFILLED'"
    )
    assert cur.fetchone()[0] == 1

    conn.close()


def test_reallocation_no_deadlock():
    """Concurrent reallocations in opposite directions must not deadlock."""
    seed(2, 2, stock=500000)
    setup_delay_trigger(0.05)

    deadlocks = 0
    NUM_TRIALS = 20

    for trial in range(NUM_TRIALS):
        o1 = trial * 2 + 1
        o2 = trial * 2 + 2
        make_order(o1, [1], wh=1, qty=1)
        make_order(o2, [1], wh=2, qty=1)

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT reserve_order_stock(%s)", (o1,))
        cur.execute("SELECT reserve_order_stock(%s)", (o2,))
        conn.close()

        errs = [None, None]
        barrier = threading.Barrier(2, timeout=15)

        def do_reallocate(oid, from_wh, to_wh, idx):
            try:
                c = psycopg2.connect(
                    dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
                )
                c.autocommit = True
                barrier.wait()
                cur = c.cursor()
                cur.execute(
                    "SELECT reallocate_reservation(%s, 1, %s, %s)",
                    (oid, from_wh, to_wh)
                )
                c.close()
            except Exception as e:
                errs[idx] = str(e)
                try:
                    c.close()
                except Exception:
                    pass

        t1 = threading.Thread(target=do_reallocate, args=(o1, 1, 2, 0))
        t2 = threading.Thread(target=do_reallocate, args=(o2, 2, 1, 1))
        t1.start()
        t2.start()
        t1.join(20)
        t2.join(20)

        for e in errs:
            if e and "deadlock" in e.lower():
                deadlocks += 1

    assert deadlocks == 0, (
        f"Deadlock in {deadlocks} of {NUM_TRIALS} concurrent reallocation trials"
    )


def test_concurrent_reallocate_cancel_no_corruption():
    """Reallocate and cancel racing on the same order must not produce constraint violations."""
    seed(3, 2, stock=500000)
    setup_delay_trigger(0.03)

    NUM_TRIALS = 20
    constraint_violations = 0

    for trial in range(NUM_TRIALS):
        oid = trial + 1
        make_order(oid, [1, 2, 3], wh=1, qty=10)

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT reserve_order_stock(%s)", (oid,))
        conn.close()

        errors = [None, None]
        barrier = threading.Barrier(2, timeout=15)

        def do_reallocate(idx):
            try:
                c = psycopg2.connect(
                    dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
                )
                c.autocommit = True
                barrier.wait()
                cur = c.cursor()
                cur.execute(
                    "SELECT reallocate_reservation(%s, 1, 1, 2)", (oid,)
                )
                c.close()
            except Exception as e:
                errors[idx] = str(e)
                try:
                    c.close()
                except Exception:
                    pass

        def do_cancel(idx):
            try:
                c = psycopg2.connect(
                    dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
                )
                c.autocommit = True
                barrier.wait()
                cur = c.cursor()
                cur.execute("SELECT cancel_order(%s)", (oid,))
                c.close()
            except Exception as e:
                errors[idx] = str(e)
                try:
                    c.close()
                except Exception:
                    pass

        t1 = threading.Thread(target=do_reallocate, args=(0,))
        t2 = threading.Thread(target=do_cancel, args=(1,))
        t1.start()
        t2.start()
        t1.join(20)
        t2.join(20)

        for e in errors:
            if e and ("violates" in e.lower() or "check constraint" in e.lower()):
                constraint_violations += 1

    assert constraint_violations == 0, (
        f"Got {constraint_violations} constraint violations in {NUM_TRIALS} trials; "
        "concurrent reallocate/cancel should produce clean status rejections"
    )

    # Verify no inventory constraint violations
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM inventory "
        "WHERE quantity_reserved < 0 OR quantity_on_hand < 0 OR quantity_reserved > quantity_on_hand"
    )
    assert cur.fetchone()[0] == 0, "Inventory constraint violation after reallocate/cancel race"

    # Verify quantity_reserved invariant
    cur.execute("""
        SELECT i.product_id, i.warehouse_id, i.quantity_reserved,
               COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0) AS active_sum
        FROM inventory i
        LEFT JOIN reservations r
            ON i.product_id = r.product_id AND i.warehouse_id = r.warehouse_id
        GROUP BY i.product_id, i.warehouse_id, i.quantity_reserved
        HAVING i.quantity_reserved != COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0)
    """)
    mismatches = cur.fetchall()
    assert len(mismatches) == 0, (
        f"Reservation quantity mismatch after reallocate/cancel race: {mismatches}"
    )
    conn.close()


def test_concurrent_reallocate_fulfill_no_corruption():
    """Reallocate and fulfill racing on the same order must not corrupt data."""
    seed(3, 2, stock=500000)
    setup_delay_trigger(0.03)

    NUM_TRIALS = 20
    constraint_violations = 0

    for trial in range(NUM_TRIALS):
        oid = trial + 1
        make_order(oid, [1, 2, 3], wh=1, qty=10)

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT reserve_order_stock(%s)", (oid,))
        conn.close()

        errors = [None, None]
        barrier = threading.Barrier(2, timeout=15)

        def do_reallocate(idx):
            try:
                c = psycopg2.connect(
                    dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
                )
                c.autocommit = True
                barrier.wait()
                cur = c.cursor()
                cur.execute(
                    "SELECT reallocate_reservation(%s, 1, 1, 2)", (oid,)
                )
                c.close()
            except Exception as e:
                errors[idx] = str(e)
                try:
                    c.close()
                except Exception:
                    pass

        def do_fulfill(idx):
            try:
                c = psycopg2.connect(
                    dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
                )
                c.autocommit = True
                barrier.wait()
                cur = c.cursor()
                cur.execute("SELECT fulfill_order(%s)", (oid,))
                c.close()
            except Exception as e:
                errors[idx] = str(e)
                try:
                    c.close()
                except Exception:
                    pass

        t1 = threading.Thread(target=do_reallocate, args=(0,))
        t2 = threading.Thread(target=do_fulfill, args=(1,))
        t1.start()
        t2.start()
        t1.join(20)
        t2.join(20)

        for e in errors:
            if e and ("violates" in e.lower() or "check constraint" in e.lower()):
                constraint_violations += 1

    assert constraint_violations == 0, (
        f"Got {constraint_violations} constraint violations in {NUM_TRIALS} trials; "
        "concurrent reallocate/fulfill should produce clean status rejections"
    )

    # Verify no inventory constraint violations
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM inventory "
        "WHERE quantity_reserved < 0 OR quantity_on_hand < 0 OR quantity_reserved > quantity_on_hand"
    )
    assert cur.fetchone()[0] == 0, "Inventory constraint violation after reallocate/fulfill race"

    # Verify quantity_reserved invariant
    cur.execute("""
        SELECT i.product_id, i.warehouse_id, i.quantity_reserved,
               COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0) AS active_sum
        FROM inventory i
        LEFT JOIN reservations r
            ON i.product_id = r.product_id AND i.warehouse_id = r.warehouse_id
        GROUP BY i.product_id, i.warehouse_id, i.quantity_reserved
        HAVING i.quantity_reserved != COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0)
    """)
    mismatches = cur.fetchall()
    assert len(mismatches) == 0, (
        f"Reservation quantity mismatch after reallocate/fulfill race: {mismatches}"
    )
    conn.close()


# ---------- batch_reserve_orders tests ----------


def test_batch_basic_all_succeed():
    """Batch reservation where all orders succeed."""
    seed(3, 1, stock=1000)
    make_order(1, [1, 2, 3], qty=5)
    make_order(2, [1, 2], qty=5)
    make_order(3, [3], qty=5)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM batch_reserve_orders(ARRAY[1, 2, 3])")
    results = cur.fetchall()

    assert len(results) == 3, f"Expected 3 result rows, got {len(results)}"
    results_dict = {r[0]: (r[1], r[2]) for r in results}

    for oid in [1, 2, 3]:
        assert results_dict[oid][0] is True, (
            f"Order {oid} should succeed, got error: {results_dict[oid][1]}"
        )

    # All orders should be RESERVED
    cur.execute("SELECT COUNT(*) FROM orders WHERE status = 'RESERVED'")
    assert cur.fetchone()[0] == 3

    # Total reserved: order1(5*3=15) + order2(5*2=10) + order3(5*1=5) = 30
    cur.execute("SELECT SUM(quantity_reserved) FROM inventory WHERE warehouse_id = 1")
    assert cur.fetchone()[0] == 30

    # Correct number of reservations
    cur.execute("SELECT COUNT(*) FROM reservations WHERE status = 'ACTIVE'")
    assert cur.fetchone()[0] == 6  # 3 + 2 + 1

    # quantity_reserved invariant
    cur.execute("""
        SELECT i.product_id, i.warehouse_id, i.quantity_reserved,
               COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0) AS active_sum
        FROM inventory i
        LEFT JOIN reservations r
            ON i.product_id = r.product_id AND i.warehouse_id = r.warehouse_id
        GROUP BY i.product_id, i.warehouse_id, i.quantity_reserved
        HAVING i.quantity_reserved != COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0)
    """)
    mismatches = cur.fetchall()
    assert len(mismatches) == 0, (
        f"quantity_reserved mismatch after batch reserve: {mismatches}"
    )
    conn.close()


def test_batch_marks_failed_status():
    """Failed orders in a batch must be marked FAILED, not left PENDING."""
    seed(1, 1, stock=10)
    make_order(1, [1], qty=15)  # needs 15, only 10 available -> fails

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM batch_reserve_orders(ARRAY[1])")
    results = cur.fetchall()

    assert len(results) == 1
    assert results[0][1] is False, "Order should have failed"

    # Order must be FAILED, not PENDING
    cur.execute("SELECT status FROM orders WHERE order_id = 1")
    status = cur.fetchone()[0]
    assert status == "FAILED", (
        f"Failed order should have status FAILED, got {status}"
    )

    # No reservations should exist
    cur.execute("SELECT COUNT(*) FROM reservations WHERE order_id = 1")
    assert cur.fetchone()[0] == 0, "Failed order should have no reservations"

    # Inventory should be unchanged
    cur.execute(
        "SELECT quantity_on_hand, quantity_reserved "
        "FROM inventory WHERE product_id = 1 AND warehouse_id = 1"
    )
    oh, res = cur.fetchone()
    assert oh == 10, f"on_hand should be unchanged (10), got {oh}"
    assert res == 0, f"reserved should be 0, got {res}"
    conn.close()


def test_batch_no_residual_on_failure():
    """A failed order in a batch must not leave partial reservations behind."""
    seed(2, 1, stock=100)
    # Order needs products [1, 2]; product 1 has 100 available,
    # product 2 we'll reduce to make the order fail on the second product
    make_order(1, [1, 2], qty=50)

    # Reduce product 2 stock to 10 so the order fails on it
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE inventory SET quantity_on_hand = 10 "
        "WHERE product_id = 2 AND warehouse_id = 1"
    )
    conn.close()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM batch_reserve_orders(ARRAY[1])")
    results = cur.fetchall()

    assert results[0][1] is False, "Order should have failed"

    # No partial reservations should remain
    cur.execute("SELECT COUNT(*) FROM reservations WHERE order_id = 1")
    res_count = cur.fetchone()[0]
    assert res_count == 0, (
        f"Failed order has {res_count} residual reservations"
    )

    # Product 1 inventory should be untouched (no partial reservation)
    cur.execute(
        "SELECT quantity_reserved FROM inventory "
        "WHERE product_id = 1 AND warehouse_id = 1"
    )
    assert cur.fetchone()[0] == 0, "Product 1 should have 0 reserved after failed order"

    # Product 2 inventory should be untouched
    cur.execute(
        "SELECT quantity_reserved FROM inventory "
        "WHERE product_id = 2 AND warehouse_id = 1"
    )
    assert cur.fetchone()[0] == 0, "Product 2 should have 0 reserved after failed order"
    conn.close()


def test_batch_cumulative_availability():
    """Within a batch, earlier orders' reservations reduce availability for later orders."""
    seed(1, 1, stock=20)
    make_order(1, [1], qty=15)  # will succeed (available=20)
    make_order(2, [1], qty=10)  # will fail (available=20-15=5 < 10)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM batch_reserve_orders(ARRAY[1, 2])")
    results = cur.fetchall()
    results_dict = {r[0]: (r[1], r[2]) for r in results}

    assert results_dict[1][0] is True, "Order 1 should succeed"
    assert results_dict[2][0] is False, "Order 2 should fail (cumulative availability)"

    # Order statuses
    cur.execute("SELECT status FROM orders WHERE order_id = 1")
    assert cur.fetchone()[0] == "RESERVED"

    cur.execute("SELECT status FROM orders WHERE order_id = 2")
    assert cur.fetchone()[0] == "FAILED"

    # Only order 1's reservation should exist
    cur.execute(
        "SELECT quantity_reserved FROM inventory "
        "WHERE product_id = 1 AND warehouse_id = 1"
    )
    assert cur.fetchone()[0] == 15, "Only order 1's reservation should be in inventory"

    # No reservations for order 2
    cur.execute("SELECT COUNT(*) FROM reservations WHERE order_id = 2")
    assert cur.fetchone()[0] == 0, "Failed order should have no reservations"

    # quantity_reserved invariant
    cur.execute("""
        SELECT i.product_id, i.warehouse_id, i.quantity_reserved,
               COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0) AS active_sum
        FROM inventory i
        LEFT JOIN reservations r
            ON i.product_id = r.product_id AND i.warehouse_id = r.warehouse_id
        GROUP BY i.product_id, i.warehouse_id, i.quantity_reserved
        HAVING i.quantity_reserved != COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0)
    """)
    mismatches = cur.fetchall()
    assert len(mismatches) == 0, (
        f"quantity_reserved mismatch after batch with partial failure: {mismatches}"
    )
    conn.close()


def test_batch_no_deadlock():
    """Concurrent batch calls with overlapping products must not deadlock."""
    seed(5, 1, stock=500000)
    setup_delay_trigger(0.05)

    deadlocks = 0
    NUM_TRIALS = 20

    for trial in range(NUM_TRIALS):
        base = trial * 4
        o1, o2, o3, o4 = base + 1, base + 2, base + 3, base + 4

        # Batch 1 orders: products in ascending order
        make_order(o1, [1, 2, 3, 4, 5], qty=1)
        make_order(o2, [3, 4, 5], qty=1)

        # Batch 2 orders: products in descending order (creates lock conflict)
        make_order(o3, [5, 4, 3, 2, 1], qty=1)
        make_order(o4, [3, 2, 1], qty=1)

        errs = [None, None]
        barrier = threading.Barrier(2, timeout=15)

        def do_batch(oids, idx):
            try:
                c = psycopg2.connect(
                    dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
                )
                c.autocommit = True
                barrier.wait()
                cur = c.cursor()
                cur.execute(
                    "SELECT * FROM batch_reserve_orders(ARRAY[%s, %s])",
                    (oids[0], oids[1])
                )
                c.close()
            except Exception as e:
                errs[idx] = str(e)
                try:
                    c.close()
                except Exception:
                    pass

        t1 = threading.Thread(target=do_batch, args=((o1, o2), 0))
        t2 = threading.Thread(target=do_batch, args=((o3, o4), 1))
        t1.start()
        t2.start()
        t1.join(20)
        t2.join(20)

        for e in errs:
            if e and "deadlock" in e.lower():
                deadlocks += 1

    assert deadlocks == 0, (
        f"Deadlock in {deadlocks} of {NUM_TRIALS} concurrent batch trials"
    )


def test_batch_concurrent_with_single_reserve():
    """A batch call and a single reserve_order_stock racing on shared products must not deadlock."""
    seed(5, 1, stock=500000)
    setup_delay_trigger(0.05)

    deadlocks = 0
    NUM_TRIALS = 20

    for trial in range(NUM_TRIALS):
        base = trial * 3
        o1, o2, o3 = base + 1, base + 2, base + 3

        # Batch: two orders with products in ascending order
        make_order(o1, [1, 2, 3], qty=1)
        make_order(o2, [4, 5], qty=1)

        # Single: order with products in descending order (overlaps with batch)
        make_order(o3, [5, 4, 3, 2, 1], qty=1)

        errs = [None, None]
        barrier = threading.Barrier(2, timeout=15)

        def do_batch(idx):
            try:
                c = psycopg2.connect(
                    dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
                )
                c.autocommit = True
                barrier.wait()
                cur = c.cursor()
                cur.execute(
                    "SELECT * FROM batch_reserve_orders(ARRAY[%s, %s])",
                    (o1, o2)
                )
                c.close()
            except Exception as e:
                errs[idx] = str(e)
                try:
                    c.close()
                except Exception:
                    pass

        def do_single(idx):
            try:
                c = psycopg2.connect(
                    dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
                )
                c.autocommit = True
                barrier.wait()
                cur = c.cursor()
                cur.execute("SELECT reserve_order_stock(%s)", (o3,))
                c.close()
            except Exception as e:
                errs[idx] = str(e)
                try:
                    c.close()
                except Exception:
                    pass

        t1 = threading.Thread(target=do_batch, args=(0,))
        t2 = threading.Thread(target=do_single, args=(1,))
        t1.start()
        t2.start()
        t1.join(20)
        t2.join(20)

        for e in errs:
            if e and "deadlock" in e.lower():
                deadlocks += 1

    assert deadlocks == 0, (
        f"Deadlock in {deadlocks} of {NUM_TRIALS} batch vs single reserve trials"
    )


# ---------- full system consistency tests ----------


def test_mixed_concurrent_consistency():
    """All procedure types running concurrently must maintain global invariants."""
    seed(5, 3, stock=50000)

    # Create 12 orders across different warehouses
    for oid in range(1, 13):
        wh = (oid % 3) + 1
        products = [((oid + j) % 5) + 1 for j in range(3)]
        make_order(oid, products, wh=wh, qty=5)

    # Reserve orders 1-10 sequentially via single reserve
    conn = get_conn()
    cur = conn.cursor()
    for oid in range(1, 11):
        cur.execute("SELECT reserve_order_stock(%s)", (oid,))
    conn.close()

    errors = []
    threads = []

    def safe_call(func_sql, args):
        try:
            c = psycopg2.connect(
                dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
            )
            c.autocommit = True
            cur = c.cursor()
            cur.execute(func_sql, args)
            c.close()
        except Exception as e:
            errors.append(str(e))
            try:
                c.close()
            except Exception:
                pass

    # Cancel orders 1-3 concurrently
    for oid in [1, 2, 3]:
        threads.append(threading.Thread(
            target=safe_call, args=("SELECT cancel_order(%s)", (oid,))
        ))

    # Fulfill orders 4-6 concurrently
    for oid in [4, 5, 6]:
        threads.append(threading.Thread(
            target=safe_call, args=("SELECT fulfill_order(%s)", (oid,))
        ))

    # Transfer stock concurrently
    transfers = [(1, 1, 2, 10), (2, 2, 3, 10), (3, 3, 1, 10), (4, 1, 3, 10), (5, 2, 1, 10)]
    for pid, fw, tw, qty in transfers:
        threads.append(threading.Thread(
            target=safe_call, args=("SELECT transfer_stock(%s, %s, %s, %s)", (pid, fw, tw, qty))
        ))

    # Reallocate reservations for orders 7-8 concurrently
    # Order 7: wh=2, products=[3,4,5] -> reallocate product 3 from W2 to W1
    threads.append(threading.Thread(
        target=safe_call,
        args=("SELECT reallocate_reservation(%s, %s, %s, %s)", (7, 3, 2, 1))
    ))
    # Order 8: wh=3, products=[4,5,1] -> reallocate product 4 from W3 to W2
    threads.append(threading.Thread(
        target=safe_call,
        args=("SELECT reallocate_reservation(%s, %s, %s, %s)", (8, 4, 3, 2))
    ))

    # Batch reserve orders 11-12 concurrently with everything else
    threads.append(threading.Thread(
        target=safe_call,
        args=("SELECT * FROM batch_reserve_orders(ARRAY[%s, %s])", (11, 12))
    ))

    # Orders 9-10 remain RESERVED with ACTIVE reservations (untouched)

    for t in threads:
        t.start()
    for t in threads:
        t.join(60)

    # No deadlocks should have occurred
    deadlocks = sum(1 for e in errors if "deadlock" in e.lower())
    assert deadlocks == 0, f"Deadlocks in mixed operations: {deadlocks}"

    # Verify all invariants
    conn = get_conn()
    cur = conn.cursor()

    # No constraint violations in inventory
    cur.execute(
        "SELECT COUNT(*) FROM inventory "
        "WHERE quantity_reserved < 0 OR quantity_on_hand < 0 OR quantity_reserved > quantity_on_hand"
    )
    violations = cur.fetchone()[0]
    assert violations == 0, f"Inventory constraint violations: {violations}"

    # quantity_reserved must match sum of ACTIVE reservations for each inventory row
    cur.execute("""
        SELECT i.product_id, i.warehouse_id, i.quantity_reserved,
               COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0) AS active_sum
        FROM inventory i
        LEFT JOIN reservations r
            ON i.product_id = r.product_id AND i.warehouse_id = r.warehouse_id
        GROUP BY i.product_id, i.warehouse_id, i.quantity_reserved
        HAVING i.quantity_reserved != COALESCE(SUM(r.quantity) FILTER (WHERE r.status = 'ACTIVE'), 0)
    """)
    mismatches = cur.fetchall()
    assert len(mismatches) == 0, (
        f"Reservation quantity mismatches (product, warehouse, reserved, active_sum): {mismatches}"
    )

    # Total stock per product must be conserved (accounting for shipments)
    for pid in range(1, 6):
        cur.execute(
            "SELECT SUM(quantity_on_hand) FROM inventory WHERE product_id = %s",
            (pid,)
        )
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM stock_movements "
            "WHERE product_id = %s AND movement_type = 'SHIPMENT'",
            (pid,)
        )
        shipped = cur.fetchone()[0]
        expected = 3 * 50000 - shipped  # 3 warehouses * 50000 initial
        assert total == expected, (
            f"Product {pid}: stock not conserved (total={total}, expected={expected}, shipped={shipped})"
        )

    # Verify batch-reserved orders are in terminal or RESERVED state
    cur.execute(
        "SELECT order_id, status FROM orders WHERE order_id IN (11, 12)"
    )
    batch_orders = cur.fetchall()
    for oid, status in batch_orders:
        assert status in ('RESERVED', 'FAILED'), (
            f"Batch order {oid} should be RESERVED or FAILED, got {status}"
        )

    # No ACTIVE reservations for FAILED orders
    cur.execute(
        "SELECT COUNT(*) FROM reservations r "
        "JOIN orders o ON r.order_id = o.order_id "
        "WHERE o.status = 'FAILED' AND r.status = 'ACTIVE'"
    )
    assert cur.fetchone()[0] == 0, "FAILED orders should have no ACTIVE reservations"

    conn.close()
