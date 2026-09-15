#!/bin/bash

set -e

# ── 0. Start PostgreSQL ──────────────────────────────────────────────────
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql
pg_ctlcluster 16 main start 2>/dev/null || true
until pg_isready -q; do sleep 1; done

DB_URL="postgres://postgres@localhost:5432/appdb?sslmode=disable&search_path=public"
DIR="file:///app/migrations"

# ── 1. Diagnose current state ────────────────────────────────────────────
echo "=== Current migration directory ==="
ls -la /app/migrations/

echo "=== Inspect schema for drift ==="
psql -U postgres -d appdb -c "\d orders"
psql -U postgres -d appdb -c "\dv"
psql -U postgres -d appdb -c "SELECT routine_name FROM information_schema.routines WHERE routine_schema='public';"
psql -U postgres -d appdb -c "\di"

# ── 2. Resolve duplicate V4 migration files ──────────────────────────────
# Two feature branches both created V4: reviews.sql (phone nullable) and
# reviews_and_phone.sql (phone NOT NULL). Keep the NOT NULL version as canonical.
rm /app/migrations/20240101000004_reviews.sql

# ── 3. Fix V4: phone NOT NULL on populated table needs DEFAULT ───────────
sed -i "s/phone VARCHAR(20) NOT NULL;/phone VARCHAR(20) NOT NULL DEFAULT '';/" \
  /app/migrations/20240101000004_reviews_and_phone.sql

# ── 4. Regenerate atlas.sum (was removed; directory modified) ────────────
atlas migrate hash --dir "$DIR"

# ── 5. Check migration status now that atlas.sum exists ──────────────────
echo "=== Atlas migration status ==="
atlas migrate status --url "$DB_URL" --dir "$DIR" 2>&1 || true

# ── 6. Remove operator drift artifacts ───────────────────────────────────
# The VIEW depends on columns we need to drop — must drop it first
psql -U postgres -d appdb -c "DROP VIEW IF EXISTS shipping_report;"
psql -U postgres -d appdb -c "DROP FUNCTION IF EXISTS calc_order_total(INTEGER);"
psql -U postgres -d appdb -c "DROP INDEX IF EXISTS idx_orders_pending;"

# Drop the operator's wrong columns (TEXT type instead of VARCHAR(500), plus spurious tracking_number)
psql -U postgres -d appdb -c "ALTER TABLE orders DROP COLUMN IF EXISTS shipping_address;"
psql -U postgres -d appdb -c "ALTER TABLE orders DROP COLUMN IF EXISTS tracking_number;"

# ── 7. Complete V3 statements 4-5 manually ───────────────────────────────
# Statement 4: shipping_address VARCHAR(500) NOT NULL — use DEFAULT for existing rows
psql -U postgres -d appdb -c \
  "ALTER TABLE orders ADD COLUMN shipping_address VARCHAR(500) NOT NULL DEFAULT 'N/A';"
psql -U postgres -d appdb -c \
  "ALTER TABLE orders ALTER COLUMN shipping_address DROP DEFAULT;"

# Statement 5: Create the missing index
psql -U postgres -d appdb -c \
  "CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);"

# ── 8. Mark V3 as fully applied in Atlas revision tracking ───────────────
atlas migrate set 20240101000003 \
  --url "$DB_URL" \
  --dir "$DIR"

# ── 9. Populate categories table for V5's foreign key constraint ─────────
# Products have category values ('Electronics', 'Gadgets') but the categories
# table is empty. V5 adds FK products(category) → categories(name).
psql -U postgres -d appdb -c \
  "INSERT INTO categories (name) SELECT DISTINCT category FROM products WHERE category IS NOT NULL;"

# ── 10. Apply all remaining migrations (V4 + V5) ────────────────────────
atlas migrate apply \
  --url "$DB_URL" \
  --dir "$DIR"

# ── 11. Verify final state ──────────────────────────────────────────────
echo ""
echo "=== Final migration status ==="
atlas migrate status --url "$DB_URL" --dir "$DIR"

echo ""
echo "=== Schema verification ==="
psql -U postgres -d appdb -c "\d users"
psql -U postgres -d appdb -c "\d orders"
psql -U postgres -d appdb -c "\d products"
psql -U postgres -d appdb -c "\d categories"
psql -U postgres -d appdb -c "\d reviews"

echo ""
echo "=== Materialized view ==="
psql -U postgres -d appdb -c "SELECT * FROM product_catalog;"

echo ""
echo "=== Data preservation ==="
psql -U postgres -d appdb -c "SELECT 'users' AS tbl, COUNT(*) FROM users
UNION ALL SELECT 'products', COUNT(*) FROM products
UNION ALL SELECT 'orders', COUNT(*) FROM orders
UNION ALL SELECT 'order_items', COUNT(*) FROM order_items
UNION ALL SELECT 'categories', COUNT(*) FROM categories;"
