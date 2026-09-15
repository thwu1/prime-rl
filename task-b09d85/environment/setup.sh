#!/bin/bash
set -e

mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql

pg_ctlcluster 16 main start

until pg_isready -q; do sleep 1; done

createdb -U postgres appdb
createdb -U postgres appdb_dev

cd /app

# Generate integrity file for V1-V3 migrations only
atlas migrate hash --dir "file:///app/migrations"

DB_URL="postgres://postgres@localhost:5432/appdb?sslmode=disable&search_path=public"
DIR="file:///app/migrations"

# Apply V1 and V2 successfully
atlas migrate apply 2 --url "$DB_URL" --dir "$DIR"

# Seed core data (users, products, orders, order_items)
psql -U postgres -d appdb -f /app/seed_data.sql

# Partially apply V3 with --tx-mode none
# Statements 1-3 succeed (add category, add description, create categories table)
# Statement 4 fails (ADD COLUMN shipping_address NOT NULL on populated table)
# Statement 5 never executes (CREATE INDEX)
atlas migrate apply 1 --url "$DB_URL" --dir "$DIR" --tx-mode none 2>&1 || true

# Now that V3 added the category/description columns, populate them
psql -U postgres -d appdb -f /app/product_categories.sql

# Apply operator's broken manual patches (wrong types, extra objects)
psql -U postgres -d appdb -f /app/operator_fix.sql

# Clean up setup artifacts so solver must inspect the database to discover drift
rm -f /app/seed_data.sql /app/product_categories.sql /app/operator_fix.sql /app/setup.sh

pg_ctlcluster 16 main stop
