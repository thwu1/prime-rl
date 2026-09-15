
import subprocess
import pytest
import psycopg2


@pytest.fixture(scope="module")
def conn():
    """Connect to the appdb database."""
    c = psycopg2.connect(
        host="localhost",
        port=5432,
        dbname="appdb",
        user="atlas",
        password="atlas",
    )
    c.autocommit = True
    yield c
    c.close()


@pytest.fixture
def cur(conn):
    cursor = conn.cursor()
    yield cursor
    cursor.close()


# ---------------------------------------------------------------------------
# 1. Migration revision table checks
# ---------------------------------------------------------------------------

def test_revision_table_exists(cur):
    """atlas_schema_revisions table must exist."""
    cur.execute(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.tables"
        "  WHERE table_schema = 'public' AND table_name = 'atlas_schema_revisions'"
        ")"
    )
    assert cur.fetchone()[0], "atlas_schema_revisions table must exist"


def test_five_migrations_recorded(cur):
    """All 5 migration versions must be recorded in the revision table."""
    cur.execute("SELECT COUNT(*) FROM atlas_schema_revisions")
    count = cur.fetchone()[0]
    assert count == 5, f"Expected 5 migration entries, found {count}"


def test_no_migration_errors(cur):
    """No migration should have a recorded error."""
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'atlas_schema_revisions' AND column_name LIKE '%error%'"
    )
    error_cols = [row[0] for row in cur.fetchall()]
    for col in error_cols:
        cur.execute(
            f"SELECT version FROM atlas_schema_revisions "
            f"WHERE {col} IS NOT NULL AND {col} != ''"
        )
        rows = cur.fetchall()
        assert len(rows) == 0, f"Migrations with errors in column '{col}': {rows}"


# ---------------------------------------------------------------------------
# 2. Table existence checks
# ---------------------------------------------------------------------------

def _table_exists(cur, table_name):
    cur.execute(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.tables"
        "  WHERE table_schema = 'public' AND table_name = %s"
        ")",
        (table_name,),
    )
    return cur.fetchone()[0]


def test_customers_table_exists(cur):
    assert _table_exists(cur, "customers"), "customers table must exist"


def test_products_table_exists(cur):
    assert _table_exists(cur, "products"), "products table must exist"


def test_orders_table_exists(cur):
    assert _table_exists(cur, "orders"), "orders table must exist"


def test_order_items_table_exists(cur):
    assert _table_exists(cur, "order_items"), "order_items table must exist"


# ---------------------------------------------------------------------------
# 3. Column structure checks
# ---------------------------------------------------------------------------

def _get_columns(cur, table_name):
    cur.execute(
        "SELECT column_name, data_type, character_maximum_length, "
        "       is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s "
        "ORDER BY ordinal_position",
        (table_name,),
    )
    return {row[0]: row for row in cur.fetchall()}


def test_customers_has_phone(cur):
    """phone column from migration 3 must exist."""
    cols = _get_columns(cur, "customers")
    assert "phone" in cols, "customers.phone column must exist"


def test_customers_name_is_varchar100(cur):
    """Drift must be resolved: customers.name must be VARCHAR(100), not TEXT."""
    cols = _get_columns(cur, "customers")
    name_col = cols.get("name")
    assert name_col is not None, "customers.name must exist"
    assert name_col[1] == "character varying", (
        f"customers.name type must be 'character varying', got '{name_col[1]}'"
    )
    assert name_col[2] == 100, (
        f"customers.name max length must be 100, got {name_col[2]}"
    )


def test_orders_has_shipping_address(cur):
    """shipping_address from migration 3 must exist and be NOT NULL."""
    cols = _get_columns(cur, "orders")
    sa = cols.get("shipping_address")
    assert sa is not None, "orders.shipping_address must exist"
    assert sa[3] == "NO", "orders.shipping_address must be NOT NULL"


def test_orders_has_total_amount(cur):
    """total_amount from migration 5 must exist."""
    cols = _get_columns(cur, "orders")
    assert "total_amount" in cols, "orders.total_amount must exist"


def test_order_items_has_discount(cur):
    """discount from migration 5 must exist."""
    cols = _get_columns(cur, "order_items")
    assert "discount" in cols, "order_items.discount must exist"


def test_products_has_sku(cur):
    """sku from migration 4 must exist."""
    cols = _get_columns(cur, "products")
    assert "sku" in cols, "products.sku must exist"


def test_products_price_no_default(cur):
    """Drift must be resolved: products.price must NOT have a DEFAULT."""
    cols = _get_columns(cur, "products")
    price = cols.get("price")
    assert price is not None, "products.price must exist"
    assert price[4] is None, (
        f"products.price should have no DEFAULT (drift resolved), got '{price[4]}'"
    )


# ---------------------------------------------------------------------------
# 4. Index checks
# ---------------------------------------------------------------------------

def _index_exists(cur, index_name):
    cur.execute(
        "SELECT EXISTS ("
        "  SELECT 1 FROM pg_indexes"
        "  WHERE schemaname = 'public' AND indexname = %s"
        ")",
        (index_name,),
    )
    return cur.fetchone()[0]


def test_idx_customers_email_exists(cur):
    """Index from migration 3 statement 4 must exist."""
    assert _index_exists(cur, "idx_customers_email"), (
        "idx_customers_email must exist"
    )


def test_idx_orders_status_exists(cur):
    """Index from migration 4 must exist."""
    assert _index_exists(cur, "idx_orders_status"), (
        "idx_orders_status must exist"
    )


def test_no_drift_index(cur):
    """Drift must be resolved: idx_orders_created must NOT exist."""
    assert not _index_exists(cur, "idx_orders_created"), (
        "idx_orders_created must not exist (was schema drift)"
    )


# ---------------------------------------------------------------------------
# 5. Data preservation checks
# ---------------------------------------------------------------------------

def test_customers_data_preserved(cur):
    cur.execute("SELECT COUNT(*) FROM customers")
    assert cur.fetchone()[0] == 3, "Must have 3 customers (seed data preserved)"


def test_products_data_preserved(cur):
    cur.execute("SELECT COUNT(*) FROM products")
    assert cur.fetchone()[0] == 3, "Must have 3 products (seed data preserved)"


def test_orders_data_preserved(cur):
    cur.execute("SELECT COUNT(*) FROM orders")
    assert cur.fetchone()[0] == 4, "Must have 4 orders (seed data preserved)"


# ---------------------------------------------------------------------------
# 6. Foreign key checks
# ---------------------------------------------------------------------------

def _fk_exists(cur, table_name, column_name):
    cur.execute(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.key_column_usage kcu"
        "  JOIN information_schema.table_constraints tc"
        "    ON kcu.constraint_name = tc.constraint_name"
        "  WHERE tc.constraint_type = 'FOREIGN KEY'"
        "    AND kcu.table_schema = 'public'"
        "    AND kcu.table_name = %s"
        "    AND kcu.column_name = %s"
        ")",
        (table_name, column_name),
    )
    return cur.fetchone()[0]


def test_orders_customer_fk(cur):
    assert _fk_exists(cur, "orders", "customer_id"), (
        "orders.customer_id FK to customers must exist"
    )


def test_order_items_order_fk(cur):
    assert _fk_exists(cur, "order_items", "order_id"), (
        "order_items.order_id FK to orders must exist"
    )


def test_order_items_product_fk(cur):
    assert _fk_exists(cur, "order_items", "product_id"), (
        "order_items.product_id FK to products must exist"
    )


# ---------------------------------------------------------------------------
# 7. Migration directory integrity
# ---------------------------------------------------------------------------

def test_atlas_migrate_status_clean():
    """atlas migrate status must succeed without errors."""
    result = subprocess.run(
        ["atlas", "migrate", "status", "--env", "local"],
        capture_output=True,
        text=True,
        cwd="/app",
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"atlas migrate status failed (rc={result.returncode}): {combined}"
    )
