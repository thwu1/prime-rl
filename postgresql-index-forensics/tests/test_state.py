
import os
import time
import pytest
import psycopg2

CONN_PARAMS = dict(
    dbname="ecommerce", user="admin", password="taskpass", host="localhost"
)


def connect_with_retry(params, retries=10, delay=2):
    """Connect to PostgreSQL with retries."""
    for attempt in range(retries):
        try:
            return psycopg2.connect(**params)
        except psycopg2.OperationalError:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise

# The full set of indexes that exist before any migration
ORIGINAL_INDEXES = {
    "orders_pkey",
    "idx_orders_customer_id",
    "idx_orders_customer_id_dup",
    "idx_orders_date_status",
    "idx_orders_date_only",
    "idx_orders_shipping_country",
    "idx_orders_total",
    "order_items_pkey",
    "idx_oi_order_id",
    "idx_oi_order_id_copy",
    "idx_oi_product_id",
    "idx_oi_product_id_dup",
    "idx_oi_quantity",
    "idx_oi_discount",
    "idx_oi_unit_price",
    "customers_pkey",
    "customers_email_key",
    "idx_customers_country",
    "idx_customers_status",
    "idx_customers_name",
    "products_pkey",
    "products_sku_key",
    "idx_products_category",
}


@pytest.fixture(scope="module")
def conn():
    c = connect_with_retry(CONN_PARAMS)
    c.autocommit = True
    yield c
    c.close()


@pytest.fixture(scope="module")
def cur(conn):
    c = conn.cursor()
    yield c
    c.close()


def _get_all_indexes(cur):
    cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
    return {row[0] for row in cur.fetchall()}


# ------------------------------------------------------------------
# Migration file existence
# ------------------------------------------------------------------


def test_migration_file_exists():
    """The migration file must exist at /app/migration.sql with meaningful content."""
    assert os.path.exists("/app/migration.sql"), "migration.sql must exist at /app/"
    with open("/app/migration.sql") as f:
        content = f.read()
    assert len(content) > 50, "migration.sql appears too short to contain a real migration"
    upper = content.upper()
    assert "DROP INDEX" in upper or "DROP" in upper, (
        "migration.sql should contain DROP INDEX statements"
    )


# ------------------------------------------------------------------
# Duplicate indexes must be removed
# ------------------------------------------------------------------


def test_duplicate_indexes_dropped(cur):
    """All exact duplicate indexes must be removed."""
    indexes = _get_all_indexes(cur)
    must_drop = {
        "idx_orders_customer_id_dup",
        "idx_oi_order_id_copy",
        "idx_oi_product_id_dup",
    }
    remaining = must_drop & indexes
    assert len(remaining) == 0, f"Duplicate indexes still present: {remaining}"


# ------------------------------------------------------------------
# Constraint indexes must be preserved
# ------------------------------------------------------------------


def test_primary_keys_preserved(cur):
    """Primary key indexes must never be dropped."""
    indexes = _get_all_indexes(cur)
    pkeys = {"orders_pkey", "order_items_pkey", "customers_pkey", "products_pkey"}
    missing = pkeys - indexes
    assert len(missing) == 0, f"Primary key indexes were dropped: {missing}"


def test_unique_constraints_preserved(cur):
    """Unique constraint indexes must never be dropped."""
    indexes = _get_all_indexes(cur)
    unique_idx = {"customers_email_key", "products_sku_key"}
    missing = unique_idx - indexes
    assert len(missing) == 0, f"Unique constraint indexes were dropped: {missing}"


# ------------------------------------------------------------------
# Actively used indexes must be preserved
# ------------------------------------------------------------------


def test_active_indexes_preserved(cur):
    """Indexes with significant scan activity must be preserved."""
    indexes = _get_all_indexes(cur)
    must_keep = {
        "idx_orders_customer_id",
        "idx_orders_date_status",
        "idx_oi_order_id",
        "idx_oi_product_id",
        "idx_products_category",
        "idx_customers_country",
    }
    missing = must_keep - indexes
    assert len(missing) == 0, f"Actively used indexes were dropped: {missing}"


# ------------------------------------------------------------------
# Unused indexes should be dropped
# ------------------------------------------------------------------


def test_unused_indexes_dropped(cur):
    """At least 5 of the 7 clearly unused indexes should be dropped."""
    indexes = _get_all_indexes(cur)
    unused = {
        "idx_orders_shipping_country",
        "idx_orders_total",
        "idx_oi_quantity",
        "idx_oi_discount",
        "idx_oi_unit_price",
        "idx_customers_status",
        "idx_customers_name",
    }
    still_present = unused & indexes
    dropped_count = len(unused) - len(still_present)
    assert dropped_count >= 5, (
        f"Only {dropped_count}/7 unused indexes dropped (need >= 5). "
        f"Still present: {still_present}"
    )


# ------------------------------------------------------------------
# Prefix-redundant index should be dropped
# ------------------------------------------------------------------


def test_redundant_prefix_index_dropped(cur):
    """idx_orders_date_only is prefix-covered by idx_orders_date_status and should be dropped."""
    indexes = _get_all_indexes(cur)
    assert "idx_orders_date_only" not in indexes, (
        "idx_orders_date_only is redundant (prefix of idx_orders_date_status) "
        "and should be dropped"
    )


# ------------------------------------------------------------------
# No remaining duplicate indexes
# ------------------------------------------------------------------


def test_no_remaining_duplicates(cur):
    """After migration, no two non-PK indexes on the same table should cover identical columns."""
    cur.execute(
        """
        WITH idx_info AS (
            SELECT i.relname   AS indexname,
                   t.relname   AS tablename,
                   ix.indkey::text AS indkey,
                   ix.indisunique
            FROM pg_index ix
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_class t ON t.oid = ix.indrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'public'
              AND NOT ix.indisprimary
        )
        SELECT tablename, indkey, array_agg(indexname ORDER BY indexname) AS names
        FROM idx_info
        GROUP BY tablename, indkey, indisunique
        HAVING count(*) > 1
        """
    )
    dups = cur.fetchall()
    assert len(dups) == 0, f"Duplicate index groups still exist: {dups}"


# ------------------------------------------------------------------
# Total index count significantly reduced
# ------------------------------------------------------------------


def test_total_index_reduction(cur):
    """Total index count should drop from 23 to at most 16."""
    indexes = _get_all_indexes(cur)
    assert len(indexes) <= 16, (
        f"Too many indexes remain ({len(indexes)}). "
        "Expected significant reduction from the original 23."
    )


# ------------------------------------------------------------------
# New index created for slow query patterns
# ------------------------------------------------------------------


def test_new_index_created(cur):
    """At least one new index must be created for identified slow query patterns."""
    current = _get_all_indexes(cur)
    new_indexes = current - ORIGINAL_INDEXES
    assert len(new_indexes) >= 1, (
        "No new indexes were created. The migration should add indexes "
        "for slow query patterns identified via pg_stat_statements."
    )


def test_pending_query_optimization(cur):
    """A new index should specifically target the slow pending-orders query pattern."""
    cur.execute(
        """
        SELECT i.relname, pg_get_indexdef(i.oid)
        FROM pg_index ix
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_class t ON t.oid = ix.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE t.relname = 'orders'
          AND n.nspname = 'public'
          AND i.relname NOT IN (
              'orders_pkey', 'idx_orders_customer_id',
              'idx_orders_customer_id_dup', 'idx_orders_date_status',
              'idx_orders_date_only', 'idx_orders_shipping_country',
              'idx_orders_total'
          )
        """
    )
    new_order_indexes = cur.fetchall()

    has_pending_optimization = False
    for _name, defn in new_order_indexes:
        defn_lower = defn.lower()
        # Accept: partial index mentioning 'pending', or index with status column
        if "pending" in defn_lower or "status" in defn_lower:
            has_pending_optimization = True
            break

    assert has_pending_optimization, (
        "No new index on orders table targets the 'status' column. "
        "Expected a partial index WHERE status='pending' or an index with "
        "status as a leading column for the slow pending-orders query."
    )
