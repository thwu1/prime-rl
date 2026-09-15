#!/usr/bin/env python3
"""
Atlas Migration Recovery Script

Diagnoses and fixes a broken Atlas migration state with:
1. Partially applied migration (txmode none + NOT NULL failure)
2. Schema drift from manual DBA interventions
3. Pending migrations waiting to be applied
"""

import subprocess
import sys
import time
import psycopg2


def run_cmd(cmd, cwd="/app", check=True):
    """Run a shell command and return the result."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=cwd
    )
    if check and result.returncode != 0:
        print(f"Command failed: {cmd}")
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")
    return result


def get_connection(retries=5):
    """Get a PostgreSQL connection with autocommit, with retries."""
    for attempt in range(retries):
        try:
            conn = psycopg2.connect(
                host="localhost",
                port=5432,
                dbname="appdb",
                user="atlas",
                password="atlas",
            )
            conn.autocommit = True
            return conn
        except psycopg2.OperationalError as e:
            if attempt < retries - 1:
                print(f"Connection attempt {attempt + 1} failed: {e}")
                time.sleep(2)
            else:
                raise


def diagnose(conn):
    """Diagnose the current state of the database and migrations."""
    print("=== DIAGNOSIS ===")

    result = run_cmd("atlas migrate status --env local", check=False)
    print(f"Atlas status:\n{result.stdout}{result.stderr}")

    cur = conn.cursor()

    # Check for schema drift: customers.name type
    cur.execute(
        "SELECT data_type, character_maximum_length "
        "FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='customers' AND column_name='name'"
    )
    row = cur.fetchone()
    if row:
        print(f"customers.name: type={row[0]}, max_length={row[1]}")
        if row[0] == "text":
            print("  -> DRIFT DETECTED: should be character varying(100)")

    # Check for extra indexes
    cur.execute(
        "SELECT indexname FROM pg_indexes "
        "WHERE schemaname='public' AND indexname='idx_orders_created'"
    )
    if cur.fetchone():
        print("  -> DRIFT DETECTED: idx_orders_created exists (not in any migration)")

    # Check for extra DEFAULT on products.price
    cur.execute(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='products' AND column_name='price'"
    )
    row = cur.fetchone()
    if row and row[0] is not None:
        print(f"  -> DRIFT DETECTED: products.price has DEFAULT={row[0]}")

    cur.close()


def fix_schema_drift(conn):
    """Revert all unauthorized manual schema changes."""
    print("\n=== FIXING SCHEMA DRIFT ===")
    cur = conn.cursor()

    # 1. Revert customers.name from TEXT back to VARCHAR(100)
    cur.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='customers' AND column_name='name'"
    )
    row = cur.fetchone()
    if row and row[0] == "text":
        print("Reverting customers.name to VARCHAR(100)...")
        cur.execute("ALTER TABLE customers ALTER COLUMN name TYPE VARCHAR(100)")

    # 2. Drop unauthorized idx_orders_created index
    cur.execute(
        "SELECT EXISTS ("
        "  SELECT 1 FROM pg_indexes "
        "  WHERE schemaname='public' AND indexname='idx_orders_created'"
        ")"
    )
    if cur.fetchone()[0]:
        print("Dropping unauthorized idx_orders_created...")
        cur.execute("DROP INDEX idx_orders_created")

    # 3. Remove unauthorized DEFAULT on products.price
    cur.execute(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='products' AND column_name='price'"
    )
    row = cur.fetchone()
    if row and row[0] is not None:
        print("Removing unauthorized DEFAULT on products.price...")
        cur.execute("ALTER TABLE products ALTER COLUMN price DROP DEFAULT")

    cur.close()
    print("Schema drift resolved.")


def fix_migration_file():
    """Fix migration 3 to handle NOT NULL column on non-empty table."""
    print("\n=== FIXING MIGRATION FILE ===")
    migration_file = "/app/migrations/20240201120000_add_order_items_fields.sql"

    with open(migration_file, "r") as f:
        content = f.read()

    # The original statement fails because it adds NOT NULL without DEFAULT
    # to a table that already has rows. Fix by adding DEFAULT ''.
    old_stmt = "ALTER TABLE orders ADD COLUMN shipping_address VARCHAR(255) NOT NULL;"
    new_stmt = "ALTER TABLE orders ADD COLUMN shipping_address VARCHAR(255) NOT NULL DEFAULT '';"

    if old_stmt in content:
        content = content.replace(old_stmt, new_stmt)
        with open(migration_file, "w") as f:
            f.write(content)
        print("Fixed: added DEFAULT '' to shipping_address column")
    else:
        print("Migration file already fixed or has different content")


def update_migration_hash():
    """Update atlas.sum after modifying migration files."""
    print("\n=== UPDATING MIGRATION HASH ===")
    result = run_cmd("atlas migrate hash --dir file://migrations")
    if result.returncode == 0:
        print("atlas.sum updated successfully.")
    else:
        print(f"Failed to update hash: {result.stderr}")
        sys.exit(1)


def complete_partial_migration(conn):
    """Manually execute remaining statements from migration 3 and reconcile revision table."""
    print("\n=== COMPLETING PARTIAL MIGRATION 3 ===")
    cur = conn.cursor()

    # Statement 3: Add shipping_address (now with DEFAULT to handle existing rows)
    cur.execute(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.columns "
        "  WHERE table_schema='public' AND table_name='orders' "
        "    AND column_name='shipping_address'"
        ")"
    )
    if not cur.fetchone()[0]:
        print("Executing statement 3: ADD COLUMN shipping_address...")
        cur.execute(
            "ALTER TABLE orders ADD COLUMN shipping_address VARCHAR(255) NOT NULL DEFAULT ''"
        )

    # Statement 4: Create index on customers(email) — use non-CONCURRENTLY here
    cur.execute(
        "SELECT EXISTS ("
        "  SELECT 1 FROM pg_indexes "
        "  WHERE schemaname='public' AND indexname='idx_customers_email'"
        ")"
    )
    if not cur.fetchone()[0]:
        print("Executing statement 4: CREATE INDEX idx_customers_email...")
        cur.execute("CREATE INDEX idx_customers_email ON customers(email)")

    # Clear the revision table so atlas migrate set can recreate it cleanly.
    # The existing entry for migration 3 has stale hash and error fields
    # from the pre-fix state. Wiping and re-setting avoids hash mismatches.
    print("Clearing stale revision entries...")
    cur.execute(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.tables "
        "  WHERE table_schema='public' AND table_name='atlas_schema_revisions'"
        ")"
    )
    if cur.fetchone()[0]:
        cur.execute("DELETE FROM atlas_schema_revisions")
    cur.close()

    # Use atlas migrate set to recreate clean revision entries for
    # all migrations up to and including 20240201120000 (migrations 1-3).
    print("Setting Atlas revision state to 20240201120000...")
    result = run_cmd("atlas migrate set 20240201120000 --env local", check=False)
    print(f"atlas migrate set output: {result.stdout}{result.stderr}")

    if result.returncode != 0:
        print("ERROR: atlas migrate set failed")
        sys.exit(1)


def apply_remaining_migrations():
    """Apply pending migrations 4 and 5."""
    print("\n=== APPLYING REMAINING MIGRATIONS ===")
    result = run_cmd("atlas migrate apply --env local", check=False)
    print(f"Apply output:\n{result.stdout}{result.stderr}")
    if result.returncode != 0:
        # If apply fails, try applying one at a time
        print("Retrying migrations individually...")
        result1 = run_cmd("atlas migrate apply 1 --env local", check=False)
        print(f"Migration 4: {result1.stdout}{result1.stderr}")
        result2 = run_cmd("atlas migrate apply 1 --env local", check=False)
        print(f"Migration 5: {result2.stdout}{result2.stderr}")


def verify(conn):
    """Verify the final state."""
    print("\n=== VERIFICATION ===")

    result = run_cmd("atlas migrate status --env local", check=False)
    print(f"Final atlas status:\n{result.stdout}{result.stderr}")

    cur = conn.cursor()

    # Check all expected tables exist
    for table in ["customers", "products", "orders", "order_items"]:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=%s)",
            (table,),
        )
        exists = cur.fetchone()[0]
        print(f"  Table {table}: {'OK' if exists else 'MISSING'}")

    # Check revision count
    cur.execute("SELECT COUNT(*) FROM atlas_schema_revisions")
    count = cur.fetchone()[0]
    print(f"  Migrations recorded: {count}")

    # Check data
    for table, expected in [("customers", 3), ("products", 3), ("orders", 4)]:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        actual = cur.fetchone()[0]
        print(f"  {table} rows: {actual} (expected {expected})")

    cur.close()


def main():
    conn = get_connection()

    diagnose(conn)
    fix_schema_drift(conn)
    fix_migration_file()
    update_migration_hash()
    complete_partial_migration(conn)
    apply_remaining_migrations()
    verify(conn)

    conn.close()
    print("\nRecovery complete.")


if __name__ == "__main__":
    main()
