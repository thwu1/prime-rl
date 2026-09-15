"""
Tests for the temporal versioning system.

"""

import json

import psycopg2
import psycopg2.errors
import psycopg2.extras
import pytest

DB_NAME = "temporal_test"


def _j(val):
    """Normalise a possibly-string JSONB value to a Python dict."""
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    return json.loads(val)


# ── fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def conn():
    c = psycopg2.connect(dbname=DB_NAME, user="postgres")
    c.autocommit = True
    yield c
    c.close()


# ── enable_versioning ─────────────────────────────────────────────────

def test_enable_products(conn):
    cur = conn.cursor()
    cur.execute("SELECT temporal.enable_versioning('public.products'::regclass)")
    cur.execute("SELECT to_regclass('public.products_history')")
    assert cur.fetchone()[0] is not None, "products_history must exist"


def test_enable_order_items(conn):
    cur = conn.cursor()
    cur.execute("SELECT temporal.enable_versioning('public.order_items'::regclass)")
    cur.execute("SELECT to_regclass('public.order_items_history')")
    assert cur.fetchone()[0] is not None, "order_items_history must exist"


def test_enable_no_pk_raises(conn):
    with pytest.raises(psycopg2.Error):
        conn.cursor().execute(
            "SELECT temporal.enable_versioning('public.log_entries'::regclass)"
        )
    conn.rollback()


def test_enable_already_tracked_raises(conn):
    """Enabling versioning on an already-tracked table must raise an exception."""
    with pytest.raises(psycopg2.Error):
        conn.cursor().execute(
            "SELECT temporal.enable_versioning('public.products'::regclass)"
        )
    conn.rollback()


def test_history_columns_products(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'products_history'
        ORDER BY ordinal_position
    """)
    cols = [r[0] for r in cur.fetchall()]
    for expected in [
        "product_id", "name", "price", "category", "is_active",
        "_valid_from", "_valid_to",
    ]:
        assert expected in cols, f"Missing column {expected} in products_history"


def test_trigger_on_products(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*) FROM pg_trigger
        WHERE tgrelid = 'public.products'::regclass AND NOT tgisinternal
    """)
    assert cur.fetchone()[0] >= 1, "Trigger must exist on products"


def test_existing_data_captured(conn):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM products_history")
    assert cur.fetchone()[0] >= 3, "Seed data (3 products) must be in history"


def test_tracked_tables_populated(conn):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM temporal.tracked_tables")
    assert cur.fetchone()[0] >= 2, "At least products and order_items tracked"


# ── INSERT tracking ───────────────────────────────────────────────────

def test_insert_creates_history(conn):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('InsTest',10.00,'t') RETURNING product_id"
    )
    pid = cur.fetchone()[0]
    cur.execute(
        "SELECT count(*) FROM products_history WHERE product_id=%s", (pid,)
    )
    assert cur.fetchone()[0] == 1


def test_insert_valid_to_infinity(conn):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('InfTest',5.00,'t') RETURNING product_id"
    )
    pid = cur.fetchone()[0]
    cur.execute(
        "SELECT _valid_to FROM products_history WHERE product_id=%s", (pid,)
    )
    vto = str(cur.fetchone()[0])
    assert "infinity" in vto.lower() or "9999" in vto, (
        f"_valid_to should be infinity, got {vto}"
    )


# ── UPDATE tracking ──────────────────────────────────────────────────

def test_update_two_history_records(conn):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('UpdTest',20.00,'t') RETURNING product_id"
    )
    pid = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("UPDATE products SET price=25.00 WHERE product_id=%s", (pid,))
    cur.execute(
        "SELECT count(*) FROM products_history WHERE product_id=%s", (pid,)
    )
    assert cur.fetchone()[0] == 2, "UPDATE must produce 2 history records"


def test_update_closes_old_opens_new(conn):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('UpdTest2',30.00,'t') RETURNING product_id"
    )
    pid = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("UPDATE products SET price=35.00 WHERE product_id=%s", (pid,))

    # exactly one closed record
    cur.execute(
        "SELECT count(*) FROM products_history "
        "WHERE product_id=%s AND _valid_to < 'infinity'::timestamptz",
        (pid,),
    )
    assert cur.fetchone()[0] == 1, "Old record must be closed"

    # the open record has the new price
    cur.execute(
        "SELECT price::float FROM products_history "
        "WHERE product_id=%s AND _valid_to = 'infinity'::timestamptz",
        (pid,),
    )
    assert cur.fetchone()[0] == 35.0


# ── DELETE tracking ──────────────────────────────────────────────────

def test_delete_closes_record(conn):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('DelTest',40.00,'t') RETURNING product_id"
    )
    pid = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("DELETE FROM products WHERE product_id=%s", (pid,))

    cur.execute(
        "SELECT count(*) FROM products_history "
        "WHERE product_id=%s AND _valid_to = 'infinity'::timestamptz",
        (pid,),
    )
    assert cur.fetchone()[0] == 0, "No open record after DELETE"

    cur.execute(
        "SELECT count(*) FROM products_history WHERE product_id=%s", (pid,)
    )
    assert cur.fetchone()[0] == 1, "Closed history record must remain"


# ── composite PK ─────────────────────────────────────────────────────

def test_composite_pk_insert(conn):
    cur = conn.cursor()
    cur.execute("INSERT INTO order_items VALUES (200,200,1,9.99)")
    cur.execute(
        "SELECT count(*) FROM order_items_history "
        "WHERE order_id=200 AND product_id=200"
    )
    assert cur.fetchone()[0] == 1


def test_composite_pk_update(conn):
    cur = conn.cursor()
    cur.execute("INSERT INTO order_items VALUES (201,201,1,19.99)")
    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute(
        "UPDATE order_items SET quantity=5 "
        "WHERE order_id=201 AND product_id=201"
    )
    cur.execute(
        "SELECT count(*) FROM order_items_history "
        "WHERE order_id=201 AND product_id=201"
    )
    assert cur.fetchone()[0] == 2


def test_composite_pk_delete(conn):
    cur = conn.cursor()
    cur.execute("INSERT INTO order_items VALUES (202,202,1,29.99)")
    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute(
        "DELETE FROM order_items WHERE order_id=202 AND product_id=202"
    )
    cur.execute(
        "SELECT count(*) FROM order_items_history "
        "WHERE order_id=202 AND product_id=202 "
        "AND _valid_to = 'infinity'::timestamptz"
    )
    assert cur.fetchone()[0] == 0


def test_composite_pk_update_isolation(conn):
    """Updating one entity must not corrupt another sharing the same first PK value."""
    cur = conn.cursor()
    # Two items in the same order (same order_id, different product_id)
    cur.execute("INSERT INTO order_items VALUES (500, 501, 1, 10.00)")
    cur.execute("INSERT INTO order_items VALUES (500, 502, 2, 20.00)")
    cur.execute("SELECT pg_sleep(0.05)")
    # Update only the first item
    cur.execute(
        "UPDATE order_items SET quantity=5 "
        "WHERE order_id=500 AND product_id=501"
    )
    # The second item must still have exactly one open history record
    cur.execute(
        "SELECT count(*) FROM order_items_history "
        "WHERE order_id=500 AND product_id=502 "
        "AND _valid_to = 'infinity'::timestamptz"
    )
    cnt = cur.fetchone()[0]
    assert cnt == 1, (
        f"Unmodified entity must retain its open history record, got {cnt}"
    )


# ── table_at ─────────────────────────────────────────────────────────

def test_table_at_sees_old_value(conn):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('TaOld',100.00,'ta') RETURNING product_id"
    )
    pid = cur.fetchone()[0]
    cur.execute(
        "SELECT _valid_from FROM products_history WHERE product_id=%s", (pid,)
    )
    t1 = cur.fetchone()[0]

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("UPDATE products SET price=200.00 WHERE product_id=%s", (pid,))

    cur.execute(
        "SELECT * FROM temporal.table_at('public.products'::regclass, %s)",
        (t1,),
    )
    found = False
    for (row,) in cur.fetchall():
        d = _j(row)
        if d.get("product_id") == pid:
            assert float(d["price"]) == 100.0
            found = True
    assert found, "Row must be visible at its original insert time"


def test_table_at_sees_new_value(conn):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('TaNew',300.00,'ta') RETURNING product_id"
    )
    pid = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("UPDATE products SET price=400.00 WHERE product_id=%s", (pid,))

    cur.execute(
        "SELECT _valid_from FROM products_history "
        "WHERE product_id=%s AND price=400.00::numeric",
        (pid,),
    )
    t2 = cur.fetchone()[0]

    cur.execute(
        "SELECT * FROM temporal.table_at('public.products'::regclass, %s)",
        (t2,),
    )
    found = False
    for (row,) in cur.fetchall():
        d = _j(row)
        if d.get("product_id") == pid:
            assert float(d["price"]) == 400.0
            found = True
    assert found, "Row must reflect the updated value"


def test_table_at_deleted_row_invisible(conn):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('TaDel',50.00,'ta') RETURNING product_id"
    )
    pid = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("DELETE FROM products WHERE product_id=%s", (pid,))

    cur.execute("SELECT clock_timestamp()")
    t_now = cur.fetchone()[0]

    cur.execute(
        "SELECT * FROM temporal.table_at('public.products'::regclass, %s)",
        (t_now,),
    )
    for (row,) in cur.fetchall():
        d = _j(row)
        assert d.get("product_id") != pid, "Deleted row must not appear"


def test_table_at_excludes_temporal_cols(conn):
    """JSONB output must contain original column names only, no temporal metadata."""
    cur = conn.cursor()
    cur.execute("SELECT clock_timestamp()")
    t = cur.fetchone()[0]
    cur.execute(
        "SELECT * FROM temporal.table_at('public.products'::regclass, %s)",
        (t,),
    )
    rows = cur.fetchall()
    assert len(rows) > 0, "Should have at least one row"
    for (row,) in rows:
        d = _j(row)
        assert "_valid_from" not in d, "JSONB must not include _valid_from"
        assert "_valid_to" not in d, "JSONB must not include _valid_to"


# ── changes_between ──────────────────────────────────────────────────

def test_changes_between_insert(conn):
    cur = conn.cursor()
    cur.execute("SELECT clock_timestamp()")
    t_before = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")

    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('CbIns',10.00,'cb') RETURNING product_id"
    )
    pid = cur.fetchone()[0]

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("SELECT clock_timestamp()")
    t_after = cur.fetchone()[0]

    cur.execute(
        "SELECT operation, pk_values FROM "
        "temporal.changes_between('public.products'::regclass, %s, %s)",
        (t_before, t_after),
    )
    ops = {}
    for op, pk in cur.fetchall():
        ops[_j(pk).get("product_id")] = op
    assert ops.get(pid) == "INSERT"


def test_changes_between_update(conn):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('CbUpd',10.00,'cb') RETURNING product_id"
    )
    pid = cur.fetchone()[0]

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("SELECT clock_timestamp()")
    t_before = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")

    cur.execute("UPDATE products SET price=99.00 WHERE product_id=%s", (pid,))

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("SELECT clock_timestamp()")
    t_after = cur.fetchone()[0]

    cur.execute(
        "SELECT operation, pk_values FROM "
        "temporal.changes_between('public.products'::regclass, %s, %s)",
        (t_before, t_after),
    )
    ops = {}
    for op, pk in cur.fetchall():
        ops[_j(pk).get("product_id")] = op
    assert ops.get(pid) == "UPDATE"


def test_changes_between_delete(conn):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('CbDel',10.00,'cb') RETURNING product_id"
    )
    pid = cur.fetchone()[0]

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("SELECT clock_timestamp()")
    t_before = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")

    cur.execute("DELETE FROM products WHERE product_id=%s", (pid,))

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("SELECT clock_timestamp()")
    t_after = cur.fetchone()[0]

    cur.execute(
        "SELECT operation, pk_values FROM "
        "temporal.changes_between('public.products'::regclass, %s, %s)",
        (t_before, t_after),
    )
    ops = {}
    for op, pk in cur.fetchall():
        ops[_j(pk).get("product_id")] = op
    assert ops.get(pid) == "DELETE"


def test_changes_between_row_data(conn):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('CbData',10.00,'cb') RETURNING product_id"
    )
    pid = cur.fetchone()[0]

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("SELECT clock_timestamp()")
    t_before = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")

    cur.execute("UPDATE products SET price=99.00 WHERE product_id=%s", (pid,))

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("SELECT clock_timestamp()")
    t_after = cur.fetchone()[0]

    cur.execute(
        "SELECT operation, pk_values, old_row, new_row FROM "
        "temporal.changes_between('public.products'::regclass, %s, %s)",
        (t_before, t_after),
    )
    for op, pk, old, new in cur.fetchall():
        if _j(pk).get("product_id") == pid:
            assert op == "UPDATE"
            assert float(_j(old)["price"]) == 10.0
            assert float(_j(new)["price"]) == 99.0
            return
    pytest.fail("Expected change row not found")


def test_changes_between_insert_null_old(conn):
    """For INSERT operations, old_row must be NULL."""
    cur = conn.cursor()
    cur.execute("SELECT clock_timestamp()")
    t_before = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")

    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('NullOld',10.00,'no') RETURNING product_id"
    )
    pid = cur.fetchone()[0]

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("SELECT clock_timestamp()")
    t_after = cur.fetchone()[0]

    cur.execute(
        "SELECT operation, pk_values, old_row, new_row FROM "
        "temporal.changes_between('public.products'::regclass, %s, %s)",
        (t_before, t_after),
    )
    for op, pk, old, new in cur.fetchall():
        if _j(pk).get("product_id") == pid:
            assert op == "INSERT"
            assert old is None, "old_row must be NULL for INSERT"
            assert new is not None, "new_row must not be NULL for INSERT"
            return
    pytest.fail("Expected INSERT change not found")


def test_changes_between_delete_null_new(conn):
    """For DELETE operations, new_row must be NULL."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('NullNew',10.00,'nn') RETURNING product_id"
    )
    pid = cur.fetchone()[0]

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("SELECT clock_timestamp()")
    t_before = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")

    cur.execute("DELETE FROM products WHERE product_id=%s", (pid,))

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("SELECT clock_timestamp()")
    t_after = cur.fetchone()[0]

    cur.execute(
        "SELECT operation, pk_values, old_row, new_row FROM "
        "temporal.changes_between('public.products'::regclass, %s, %s)",
        (t_before, t_after),
    )
    for op, pk, old, new in cur.fetchall():
        if _j(pk).get("product_id") == pid:
            assert op == "DELETE"
            assert old is not None, "old_row must not be NULL for DELETE"
            assert new is None, "new_row must be NULL for DELETE"
            return
    pytest.fail("Expected DELETE change not found")


def test_changes_between_unchanged_excluded(conn):
    """Entities present at both timestamps with identical values must not appear."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('Stable',50.00,'st') RETURNING product_id"
    )
    pid_stable = cur.fetchone()[0]

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("SELECT clock_timestamp()")
    t_before = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")

    # Insert a new product but do NOT modify the stable one
    cur.execute(
        "INSERT INTO products (name,price,category) "
        "VALUES ('Fresh',60.00,'st') RETURNING product_id"
    )
    pid_fresh = cur.fetchone()[0]

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("SELECT clock_timestamp()")
    t_after = cur.fetchone()[0]

    cur.execute(
        "SELECT operation, pk_values FROM "
        "temporal.changes_between('public.products'::regclass, %s, %s)",
        (t_before, t_after),
    )
    pids = {}
    for op, pk in cur.fetchall():
        d = _j(pk)
        pids[d.get("product_id")] = op

    assert pid_fresh in pids, "Newly inserted product must appear"
    assert pid_stable not in pids, "Unchanged product must not appear"


def test_changes_between_composite_pk(conn):
    cur = conn.cursor()
    cur.execute("SELECT clock_timestamp()")
    t_before = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")

    cur.execute("INSERT INTO order_items VALUES (300,300,1,5.00)")

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("SELECT clock_timestamp()")
    t_after = cur.fetchone()[0]

    cur.execute(
        "SELECT operation, pk_values FROM "
        "temporal.changes_between('public.order_items'::regclass, %s, %s)",
        (t_before, t_after),
    )
    found = False
    for op, pk in cur.fetchall():
        d = _j(pk)
        if d.get("order_id") == 300 and d.get("product_id") == 300:
            assert op == "INSERT"
            found = True
    assert found, "Composite-PK INSERT must appear in changes_between"


# ── disable / re-enable ──────────────────────────────────────────────

def test_disable_versioning(conn):
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE disable_test (id serial PRIMARY KEY, val text)"
    )
    cur.execute(
        "SELECT temporal.enable_versioning('public.disable_test'::regclass)"
    )
    cur.execute("INSERT INTO disable_test (val) VALUES ('hello')")

    cur.execute(
        "SELECT temporal.disable_versioning('public.disable_test'::regclass)"
    )

    cur.execute("SELECT to_regclass('public.disable_test_history')")
    assert cur.fetchone()[0] is None, "History table must be dropped"

    cur.execute(
        "SELECT count(*) FROM pg_trigger "
        "WHERE tgrelid = 'public.disable_test'::regclass AND NOT tgisinternal"
    )
    assert cur.fetchone()[0] == 0, "Trigger must be removed"

    cur.execute(
        "SELECT count(*) FROM temporal.tracked_tables "
        "WHERE table_name = 'disable_test'"
    )
    assert cur.fetchone()[0] == 0, "Tracking entry must be removed"


def test_disable_not_tracked_raises(conn):
    """disable_versioning on an untracked table must raise an exception."""
    with pytest.raises(psycopg2.Error):
        conn.cursor().execute(
            "SELECT temporal.disable_versioning('public.log_entries'::regclass)"
        )
    conn.rollback()


def test_re_enable_after_disable(conn):
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE reenable_test (id serial PRIMARY KEY, val text)"
    )
    cur.execute("INSERT INTO reenable_test (val) VALUES ('seed')")

    # enable -> insert -> disable -> re-enable -> insert
    cur.execute(
        "SELECT temporal.enable_versioning('public.reenable_test'::regclass)"
    )
    cur.execute("INSERT INTO reenable_test (val) VALUES ('v1')")
    cur.execute(
        "SELECT temporal.disable_versioning('public.reenable_test'::regclass)"
    )
    cur.execute(
        "SELECT temporal.enable_versioning('public.reenable_test'::regclass)"
    )
    cur.execute("INSERT INTO reenable_test (val) VALUES ('v2')")

    cur.execute("SELECT count(*) FROM reenable_test_history")
    cnt = cur.fetchone()[0]
    # After re-enable: existing rows (seed, v1) captured + new insert (v2)
    assert cnt >= 3, f"Expected >= 3 history rows after re-enable, got {cnt}"


# ── merge_history ─────────────────────────────────────────────────────

def test_merge_reduces_records(conn):
    """Consecutive identical updates should merge into one record (chain of 3)."""
    cur = conn.cursor()
    cur.execute("CREATE TABLE merge_same (id serial PRIMARY KEY, val text)")
    cur.execute(
        "SELECT temporal.enable_versioning('public.merge_same'::regclass)"
    )

    cur.execute("INSERT INTO merge_same (val) VALUES ('x') RETURNING id")
    mid = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("UPDATE merge_same SET val='x' WHERE id=%s", (mid,))
    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("UPDATE merge_same SET val='x' WHERE id=%s", (mid,))

    cur.execute(
        "SELECT count(*) FROM merge_same_history WHERE id=%s", (mid,)
    )
    before = cur.fetchone()[0]
    assert before == 3, f"Expected 3 records before merge, got {before}"

    cur.execute(
        "SELECT temporal.merge_history('public.merge_same'::regclass)"
    )
    removed = cur.fetchone()[0]

    cur.execute(
        "SELECT count(*) FROM merge_same_history WHERE id=%s", (mid,)
    )
    after = cur.fetchone()[0]
    assert after == 1, f"Expected 1 record after merge, got {after}"
    assert removed == 2, f"Expected 2 records removed, got {removed}"


def test_merge_preserves_different(conn):
    """Records with different values must not be merged."""
    cur = conn.cursor()
    cur.execute("CREATE TABLE merge_diff (id serial PRIMARY KEY, val text)")
    cur.execute(
        "SELECT temporal.enable_versioning('public.merge_diff'::regclass)"
    )

    cur.execute("INSERT INTO merge_diff (val) VALUES ('a') RETURNING id")
    mid = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("UPDATE merge_diff SET val='b' WHERE id=%s", (mid,))
    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("UPDATE merge_diff SET val='c' WHERE id=%s", (mid,))

    cur.execute(
        "SELECT count(*) FROM merge_diff_history WHERE id=%s", (mid,)
    )
    before = cur.fetchone()[0]
    assert before == 3

    cur.execute(
        "SELECT temporal.merge_history('public.merge_diff'::regclass)"
    )
    removed = cur.fetchone()[0]

    cur.execute(
        "SELECT count(*) FROM merge_diff_history WHERE id=%s", (mid,)
    )
    after = cur.fetchone()[0]
    assert after == before, "Records with different values must not be merged"
    assert removed == 0


def test_merge_temporal_correctness(conn):
    """After merging, table_at still returns correct results at intermediate timestamps."""
    cur = conn.cursor()
    cur.execute("CREATE TABLE merge_verify (id serial PRIMARY KEY, val text)")
    cur.execute(
        "SELECT temporal.enable_versioning('public.merge_verify'::regclass)"
    )

    cur.execute("INSERT INTO merge_verify (val) VALUES ('v') RETURNING id")
    mid = cur.fetchone()[0]

    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("SELECT clock_timestamp()")
    t_mid = cur.fetchone()[0]
    cur.execute("SELECT pg_sleep(0.05)")

    cur.execute("UPDATE merge_verify SET val='v' WHERE id=%s", (mid,))
    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute("UPDATE merge_verify SET val='w' WHERE id=%s", (mid,))

    # Before merge: 'v' at t1-t2, 'v' at t2-t3, 'w' at t3-inf
    # Merge collapses first two into 'v' at t1-t3
    cur.execute(
        "SELECT temporal.merge_history('public.merge_verify'::regclass)"
    )

    # At t_mid (between t1 and t2), val should be 'v'
    cur.execute(
        "SELECT * FROM temporal.table_at('public.merge_verify'::regclass, %s)",
        (t_mid,),
    )
    found = False
    for (row,) in cur.fetchall():
        d = _j(row)
        if d.get("id") == mid:
            assert d["val"] == "v", f"Expected 'v' at t_mid, got {d['val']}"
            found = True
    assert found, "Row must be visible at intermediate timestamp after merge"


def test_merge_composite_pk(conn):
    """merge_history works correctly for composite PK tables."""
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE merge_comp ("
        "  a_id integer NOT NULL, b_id integer NOT NULL, val text, "
        "  PRIMARY KEY (a_id, b_id))"
    )
    cur.execute(
        "SELECT temporal.enable_versioning('public.merge_comp'::regclass)"
    )

    cur.execute("INSERT INTO merge_comp VALUES (10, 20, 'keep')")
    cur.execute("SELECT pg_sleep(0.05)")
    cur.execute(
        "UPDATE merge_comp SET val='keep' WHERE a_id=10 AND b_id=20"
    )

    cur.execute(
        "SELECT count(*) FROM merge_comp_history "
        "WHERE a_id=10 AND b_id=20"
    )
    before = cur.fetchone()[0]
    assert before == 2, f"Expected 2 records before merge, got {before}"

    cur.execute(
        "SELECT temporal.merge_history('public.merge_comp'::regclass)"
    )
    removed = cur.fetchone()[0]

    cur.execute(
        "SELECT count(*) FROM merge_comp_history "
        "WHERE a_id=10 AND b_id=20"
    )
    after = cur.fetchone()[0]
    assert after == 1, f"Expected 1 record after merge, got {after}"
    assert removed == 1
