import subprocess
import os



def run_sql(query):
    """Execute a SQL query against appdb and return trimmed output."""
    result = subprocess.run(
        ["psql", "-U", "postgres", "-d", "appdb", "-t", "-A", "-c", query],
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def get_columns(table):
    """Return list of column names for a table."""
    raw = run_sql(
        f"SELECT column_name FROM information_schema.columns "
        f"WHERE table_name='{table}' AND table_schema='public' "
        f"ORDER BY ordinal_position"
    )
    return [c.strip() for c in raw.split("\n") if c.strip()]


# ---------------------------------------------------------------------------
# PostgreSQL accessibility
# ---------------------------------------------------------------------------

class TestPostgresRunning:
    def test_pg_is_ready(self):
        result = subprocess.run(["pg_isready"], capture_output=True, text=True)
        assert result.returncode == 0, "PostgreSQL is not running"


# ---------------------------------------------------------------------------
# users table (V1 + V2 + V4 columns)
# ---------------------------------------------------------------------------

class TestUsersTable:
    def test_columns_present(self):
        cols = get_columns("users")
        for c in ["id", "username", "email", "created_at", "full_name", "phone"]:
            assert c in cols, f"users missing column '{c}'"

    def test_phone_type(self):
        row = run_sql(
            "SELECT data_type, character_maximum_length "
            "FROM information_schema.columns "
            "WHERE table_name='users' AND column_name='phone' "
            "AND table_schema='public'"
        )
        assert "character varying" in row, f"Expected VARCHAR type for phone, got: {row}"
        assert "20" in row, f"Expected max_length 20 for phone, got: {row}"

    def test_phone_not_null(self):
        nullable = run_sql(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='users' AND column_name='phone' "
            "AND table_schema='public'"
        )
        assert nullable == "NO", f"phone must be NOT NULL, got is_nullable={nullable}"

    def test_data_preserved(self):
        n = int(run_sql("SELECT COUNT(*) FROM users"))
        assert n >= 3, f"Expected >= 3 users, got {n}"


# ---------------------------------------------------------------------------
# products table (V1 + V3 columns + V5 FK)
# ---------------------------------------------------------------------------

class TestProductsTable:
    def test_columns_present(self):
        cols = get_columns("products")
        for c in ["id", "name", "price", "stock", "created_at", "category", "description"]:
            assert c in cols, f"products missing column '{c}'"

    def test_data_preserved(self):
        n = int(run_sql("SELECT COUNT(*) FROM products"))
        assert n >= 3, f"Expected >= 3 products, got {n}"

    def test_category_index_exists(self):
        cnt = run_sql(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE tablename='products' AND indexname='idx_products_category'"
        )
        assert cnt == "1", "idx_products_category index is missing"

    def test_fk_products_category_exists(self):
        cnt = run_sql(
            "SELECT COUNT(*) FROM information_schema.table_constraints "
            "WHERE constraint_name='fk_products_category' "
            "AND table_name='products' AND constraint_type='FOREIGN KEY'"
        )
        assert cnt == "1", "FK constraint fk_products_category is missing on products"


# ---------------------------------------------------------------------------
# orders table (V1 + V3 shipping_address, NO operator drift)
# ---------------------------------------------------------------------------

class TestOrdersTable:
    def test_expected_columns(self):
        cols = get_columns("orders")
        for c in ["id", "user_id", "total", "status", "created_at", "shipping_address"]:
            assert c in cols, f"orders missing column '{c}'"

    def test_shipping_address_type_varchar500(self):
        row = run_sql(
            "SELECT data_type, character_maximum_length "
            "FROM information_schema.columns "
            "WHERE table_name='orders' AND column_name='shipping_address' "
            "AND table_schema='public'"
        )
        assert row, "shipping_address column does not exist"
        assert "character varying" in row, f"Expected VARCHAR type, got: {row}"
        assert "500" in row, f"Expected max_length 500, got: {row}"

    def test_shipping_address_not_null(self):
        nullable = run_sql(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='orders' AND column_name='shipping_address' "
            "AND table_schema='public'"
        )
        assert nullable == "NO", (
            f"shipping_address must be NOT NULL, got is_nullable={nullable}"
        )

    def test_no_tracking_number(self):
        cnt = run_sql(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_name='orders' AND column_name='tracking_number' "
            "AND table_schema='public'"
        )
        assert cnt == "0", "tracking_number column must not exist (operator drift)"

    def test_data_preserved(self):
        n = int(run_sql("SELECT COUNT(*) FROM orders"))
        assert n >= 3, f"Expected >= 3 orders, got {n}"

    def test_shipping_address_values_populated(self):
        nulls = int(run_sql(
            "SELECT COUNT(*) FROM orders WHERE shipping_address IS NULL"
        ))
        assert nulls == 0, f"Found {nulls} orders with NULL shipping_address"


# ---------------------------------------------------------------------------
# Operator drift artifacts must be removed
# ---------------------------------------------------------------------------

class TestNoDriftArtifacts:
    def test_no_shipping_report_view(self):
        cnt = run_sql(
            "SELECT COUNT(*) FROM information_schema.views "
            "WHERE table_name='shipping_report' AND table_schema='public'"
        )
        assert cnt == "0", "shipping_report VIEW must not exist (operator drift)"

    def test_no_calc_order_total_function(self):
        cnt = run_sql(
            "SELECT COUNT(*) FROM information_schema.routines "
            "WHERE routine_name='calc_order_total' AND routine_schema='public'"
        )
        assert cnt == "0", "calc_order_total FUNCTION must not exist (operator drift)"

    def test_no_idx_orders_pending(self):
        cnt = run_sql(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE indexname='idx_orders_pending'"
        )
        assert cnt == "0", "idx_orders_pending index must not exist (operator drift)"


# ---------------------------------------------------------------------------
# order_items table (V2)
# ---------------------------------------------------------------------------

class TestOrderItemsTable:
    def test_columns_present(self):
        cols = get_columns("order_items")
        for c in ["id", "order_id", "product_id", "quantity", "unit_price"]:
            assert c in cols, f"order_items missing column '{c}'"

    def test_data_preserved(self):
        n = int(run_sql("SELECT COUNT(*) FROM order_items"))
        assert n >= 3, f"Expected >= 3 order_items, got {n}"


# ---------------------------------------------------------------------------
# categories table (V3 + V5 UNIQUE constraint)
# ---------------------------------------------------------------------------

class TestCategoriesTable:
    def test_columns_present(self):
        cols = get_columns("categories")
        for c in ["id", "name", "parent_id"]:
            assert c in cols, f"categories missing column '{c}'"

    def test_unique_constraint_on_name(self):
        cnt = run_sql(
            "SELECT COUNT(*) FROM information_schema.table_constraints "
            "WHERE table_name='categories' AND constraint_type='UNIQUE' "
            "AND table_schema='public'"
        )
        assert int(cnt) >= 1, "categories table missing UNIQUE constraint on name"

    def test_has_category_data(self):
        n = int(run_sql("SELECT COUNT(*) FROM categories"))
        assert n >= 2, f"Expected >= 2 categories rows, got {n}"

    def test_all_product_categories_have_matching_entry(self):
        orphans = int(run_sql(
            "SELECT COUNT(*) FROM products p "
            "WHERE p.category IS NOT NULL "
            "AND p.category NOT IN (SELECT name FROM categories)"
        ))
        assert orphans == 0, (
            f"Found {orphans} products with category values not in categories table"
        )


# ---------------------------------------------------------------------------
# reviews table (V4)
# ---------------------------------------------------------------------------

class TestReviewsTable:
    def test_columns_present(self):
        cols = get_columns("reviews")
        for c in ["id", "user_id", "product_id", "rating", "comment", "created_at"]:
            assert c in cols, f"reviews missing column '{c}'"

    def test_rating_check_constraint(self):
        cnt = int(run_sql(
            "SELECT COUNT(*) FROM information_schema.check_constraints cc "
            "JOIN information_schema.table_constraints tc "
            "  ON cc.constraint_name = tc.constraint_name "
            "WHERE tc.table_name = 'reviews' "
            "  AND tc.table_schema = 'public' "
            "  AND cc.check_clause LIKE '%rating%'"
        ))
        assert cnt >= 1, "reviews table missing CHECK constraint on rating"


# ---------------------------------------------------------------------------
# product_catalog materialized view (V5)
# ---------------------------------------------------------------------------

class TestProductCatalogView:
    def test_materialized_view_exists(self):
        cnt = run_sql(
            "SELECT COUNT(*) FROM pg_matviews "
            "WHERE matviewname='product_catalog' AND schemaname='public'"
        )
        assert cnt == "1", "product_catalog materialized view is missing"

    def test_materialized_view_has_data(self):
        n = int(run_sql("SELECT COUNT(*) FROM product_catalog"))
        assert n >= 3, f"Expected >= 3 rows in product_catalog, got {n}"


# ---------------------------------------------------------------------------
# Atlas migration state
# ---------------------------------------------------------------------------

class TestAtlasMigrationState:
    def test_no_partial_migrations(self):
        """atlas migrate status must not report any partially-applied file."""
        result = subprocess.run(
            [
                "atlas", "migrate", "status",
                "--url", "postgres://postgres@localhost:5432/appdb?sslmode=disable&search_path=public",
                "--dir", "file:///app/migrations",
            ],
            capture_output=True, text=True,
        )
        combined = (result.stdout + result.stderr).lower()
        assert "partially" not in combined, (
            f"Partial migration detected:\n{result.stdout}\n{result.stderr}"
        )

    def test_status_exits_cleanly(self):
        """atlas migrate status should exit 0 when everything is applied."""
        result = subprocess.run(
            [
                "atlas", "migrate", "status",
                "--url", "postgres://postgres@localhost:5432/appdb?sslmode=disable&search_path=public",
                "--dir", "file:///app/migrations",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"atlas migrate status exited {result.returncode}:\n"
            f"{result.stdout}\n{result.stderr}"
        )

    def test_all_five_migrations_applied(self):
        """All 5 migrations must be recorded in Atlas revision tracking."""
        result = subprocess.run(
            [
                "atlas", "migrate", "status",
                "--url", "postgres://postgres@localhost:5432/appdb?sslmode=disable&search_path=public",
                "--dir", "file:///app/migrations",
            ],
            capture_output=True, text=True,
        )
        combined = result.stdout + result.stderr
        # The last migration version must appear as current/applied
        assert "20240101000005" in combined, (
            f"Latest migration 20240101000005 not found in status output:\n{combined}"
        )

    def test_no_duplicate_version_files(self):
        """Migration directory must not contain duplicate version numbers."""
        import glob
        files = glob.glob("/app/migrations/20240101000004_*.sql")
        assert len(files) == 1, (
            f"Expected exactly 1 file with version 20240101000004, found {len(files)}: {files}"
        )


# ---------------------------------------------------------------------------
# Migration directory integrity (atlas.sum must match files)
# ---------------------------------------------------------------------------

class TestMigrationDirectoryIntegrity:
    def test_atlas_sum_is_current(self):
        """atlas.sum must match the migration files.

        If the solver modified any migration file without running
        'atlas migrate hash', this test will fail.
        """
        sum_path = "/app/migrations/atlas.sum"
        assert os.path.exists(sum_path), "atlas.sum file is missing"

        with open(sum_path) as f:
            original_sum = f.read()

        result = subprocess.run(
            ["atlas", "migrate", "hash", "--dir", "file:///app/migrations"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"atlas migrate hash failed: {result.stderr}"
        )

        with open(sum_path) as f:
            regenerated_sum = f.read()

        assert original_sum == regenerated_sum, (
            "atlas.sum is stale — migration files were modified without "
            "running 'atlas migrate hash' to update the integrity file"
        )
