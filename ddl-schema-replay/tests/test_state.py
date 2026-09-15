
"""
Verify that schema_state contains the correct final schema after
replaying 25 MySQL DDL statements from ddl_history.
"""

import pytest
import psycopg2


@pytest.fixture(scope="module")
def db():
    conn = psycopg2.connect(
        dbname="cdc", user="cdc", password="cdc", host="localhost"
    )
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def schema_data(db):
    """Load all schema_state rows into a nested dict: table -> col -> attrs."""
    cur = db.cursor()
    cur.execute(
        "SELECT table_name, column_name, ordinal_position, data_type, "
        "is_nullable, column_default, is_primary_key, is_generated "
        "FROM schema_state ORDER BY table_name, ordinal_position"
    )
    rows = cur.fetchall()
    cur.close()
    result = {}
    for tn, cn, op, dt, nu, cd, pk, gen in rows:
        if tn not in result:
            result[tn] = {}
        result[tn][cn] = {
            "ordinal_position": op,
            "data_type": dt,
            "is_nullable": nu,
            "column_default": cd,
            "is_primary_key": pk,
            "is_generated": gen,
        }
    return result


# ── Expected schema state ──────────────────────────────────────────

EXPECTED_TABLES = {
    "customers",
    "catalog_items",
    "orders",
    "change_log",
    "inventory",
    "order_lines",
}

# (column_name, ordinal, data_type, is_nullable, column_default, is_pk, is_generated)
EXPECTED_CUSTOMERS = [
    ("tenant_id",   1, "int",       False, "1",                 False, False),
    ("id",          2, "bigint",    False, None,                True,  False),
    ("name",        3, "varchar(100)", False, None,             False, False),
    ("email",       4, "varchar(255)", False, None,             False, False),
    ("mobile",      5, "varchar(20)", True,  None,              False, False),
    ("status",      6, "enum('ACTIVE','INACTIVE','SUSPENDED','BANNED','DELETED')",
                                     False, "ACTIVE",           False, False),
    ("created_at",  7, "timestamp", False, "CURRENT_TIMESTAMP", False, False),
    ("updated_at",  8, "timestamp", False, "CURRENT_TIMESTAMP", False, False),
]

EXPECTED_CATALOG_ITEMS = [
    ("product_id",  1, "bigint unsigned", False, None,   False, False),
    ("sku",         2, "varchar(50)",     False, None,   True,  False),
    ("title",       3, "varchar(255)",    False, "",     False, False),
    ("description", 4, "text",            True,  None,   False, False),
    ("price",       5, "decimal(12,2)",   False, "0.00", False, False),
    ("weight_g",    6, "int unsigned",    True,  None,   False, False),
    ("is_active",   7, "tinyint(1)",      False, "1",    False, False),
    ("cost_price",  8, "decimal(10,2)",   True,  None,   False, False),
    ("margin_pct",  9, "decimal(5,2)",    True,  None,   False, True),
]

EXPECTED_ORDERS = [
    ("order_id",       1, "bigint unsigned", False, None,                  True,  False),
    ("customer_id",    2, "bigint",          False, None,                  False, False),
    ("order_total",    3, "decimal(20,4)",   False, "0.0000",              False, False),
    ("currency",       4, "char(3)",         False, "USD",                 False, False),
    ("payment_method", 5, "set('CREDIT_CARD','DEBIT_CARD','PAYPAL','WIRE','CRYPTO')",
                                             True,  None,                  False, False),
    ("placed_at",      6, "datetime(6)",     False, "CURRENT_TIMESTAMP(6)", False, False),
    ("notes",          7, "text",            True,  None,                  False, False),
]

EXPECTED_CHANGE_LOG = [
    ("id",           1, "bigint",       False, None,                  True,  False),
    ("target_table", 2, "varchar(255)", False, None,                  False, False),
    ("target_id",    3, "bigint",       False, None,                  False, False),
    ("before_state", 4, "longtext",     False, "json_object()",       False, False),
    ("after_state",  5, "longtext",     False, "json_object()",       False, False),
    ("changed_at",   6, "timestamp",    False, "current_timestamp()", False, False),
    ("event_uuid",   7, "varchar(36)",  False, "UUID()",              False, False),
    ("actor_id",     8, "bigint",       True,  None,                  False, False),
    ("actor_type",   9, "enum('USER','SYSTEM','API','WEBHOOK')",
                                        False, "USER",                False, False),
]

EXPECTED_INVENTORY = [
    ("id",              1, "bigint unsigned", False, None,                True,  False),
    ("product_id",      2, "bigint unsigned", False, None,                False, False),
    ("warehouse",       3, "varchar(50)",     False, None,                False, False),
    ("quantity",        4, "int",             False, "0",                 False, False),
    ("reserved",        5, "int unsigned",    False, "0",                 False, False),
    ("available",       6, "int",             True,  None,                False, True),
    ("last_counted_at", 7, "datetime",        True,  "curtime()",         False, False),
    ("updated_at",      8, "timestamp",       False, "CURRENT_TIMESTAMP", False, False),
]

EXPECTED_ORDER_LINES = [
    ("line_id",     1, "bigint",          False, None,   True,  False),
    ("order_id",    2, "bigint unsigned", False, None,   False, False),
    ("product_sku", 3, "varchar(50)",     False, None,   False, False),
    ("quantity",    4, "smallint unsigned", False, "1",   False, False),
    ("unit_price",  5, "decimal(12,2)",   False, None,   False, False),
    ("line_total",  6, "decimal(14,2)",   True,  None,   False, True),
    ("discount_pct", 7, "decimal(5,2)",   False, "0.00", False, False),
    ("net_total",   8, "decimal(14,2)",   True,  None,   False, True),
]


ALL_EXPECTED = {
    "customers": EXPECTED_CUSTOMERS,
    "catalog_items": EXPECTED_CATALOG_ITEMS,
    "orders": EXPECTED_ORDERS,
    "change_log": EXPECTED_CHANGE_LOG,
    "inventory": EXPECTED_INVENTORY,
    "order_lines": EXPECTED_ORDER_LINES,
}


# ── Tests ──────────────────────────────────────────────────────────


class TestSchemaStateTables:
    """Verify that exactly the expected tables are present."""

    def test_schema_state_table_exists(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_name = 'schema_state' AND table_schema = 'public'"
            ")"
        )
        assert cur.fetchone()[0], "schema_state table does not exist"
        cur.close()

    def test_expected_tables_present(self, schema_data):
        actual = set(schema_data.keys())
        assert EXPECTED_TABLES == actual, (
            f"Table set mismatch.\n"
            f"  Missing: {EXPECTED_TABLES - actual}\n"
            f"  Extra:   {actual - EXPECTED_TABLES}"
        )


def _assert_table_columns(schema_data, table_name, expected_cols):
    """Helper: verify all columns for a single table."""
    assert table_name in schema_data, f"Table '{table_name}' missing from schema_state"
    actual_cols = schema_data[table_name]
    expected_names = {c[0] for c in expected_cols}
    actual_names = set(actual_cols.keys())
    assert expected_names == actual_names, (
        f"Column set mismatch for '{table_name}'.\n"
        f"  Missing: {expected_names - actual_names}\n"
        f"  Extra:   {actual_names - expected_names}"
    )
    for col_name, ordinal, dtype, nullable, default, is_pk, is_gen in expected_cols:
        a = actual_cols[col_name]
        assert a["ordinal_position"] == ordinal, (
            f"{table_name}.{col_name}: ordinal_position expected {ordinal}, got {a['ordinal_position']}"
        )
        assert a["data_type"] == dtype, (
            f"{table_name}.{col_name}: data_type expected '{dtype}', got '{a['data_type']}'"
        )
        assert a["is_nullable"] == nullable, (
            f"{table_name}.{col_name}: is_nullable expected {nullable}, got {a['is_nullable']}"
        )
        if default is None:
            assert a["column_default"] is None, (
                f"{table_name}.{col_name}: column_default expected NULL, got '{a['column_default']}'"
            )
        else:
            assert a["column_default"] == default, (
                f"{table_name}.{col_name}: column_default expected '{default}', got '{a['column_default']}'"
            )
        assert a["is_primary_key"] == is_pk, (
            f"{table_name}.{col_name}: is_primary_key expected {is_pk}, got {a['is_primary_key']}"
        )
        assert a["is_generated"] == is_gen, (
            f"{table_name}.{col_name}: is_generated expected {is_gen}, got {a['is_generated']}"
        )


class TestCustomers:
    def test_columns(self, schema_data):
        _assert_table_columns(schema_data, "customers", EXPECTED_CUSTOMERS)


class TestCatalogItems:
    def test_columns(self, schema_data):
        _assert_table_columns(schema_data, "catalog_items", EXPECTED_CATALOG_ITEMS)


class TestOrders:
    def test_columns(self, schema_data):
        _assert_table_columns(schema_data, "orders", EXPECTED_ORDERS)


class TestChangeLog:
    def test_columns(self, schema_data):
        _assert_table_columns(schema_data, "change_log", EXPECTED_CHANGE_LOG)


class TestInventory:
    def test_columns(self, schema_data):
        _assert_table_columns(schema_data, "inventory", EXPECTED_INVENTORY)


class TestOrderLines:
    def test_columns(self, schema_data):
        _assert_table_columns(schema_data, "order_lines", EXPECTED_ORDER_LINES)


class TestRowCounts:
    """Verify exact row counts per table — no extra columns."""

    @pytest.mark.parametrize("table_name,expected_count", [
        ("customers", 8),
        ("catalog_items", 9),
        ("orders", 7),
        ("change_log", 9),
        ("inventory", 8),
        ("order_lines", 8),
    ])
    def test_column_count(self, schema_data, table_name, expected_count):
        actual = len(schema_data.get(table_name, {}))
        assert actual == expected_count, (
            f"Table '{table_name}' has {actual} columns, expected {expected_count}"
        )

    def test_total_rows(self, db):
        cur = db.cursor()
        cur.execute("SELECT count(*) FROM schema_state")
        total = cur.fetchone()[0]
        cur.close()
        assert total == 49, f"schema_state has {total} rows, expected 49"
