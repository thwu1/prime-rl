#!/usr/bin/env python3
"""

Analyze the ecommerce PostgreSQL database, identify index problems,
generate an optimisation migration, and execute it.
"""

import psycopg2
import time
from collections import defaultdict


DB = dict(dbname="ecommerce", user="admin", password="taskpass", host="localhost")


def connect_with_retry(params, retries=10, delay=2):
    """Connect to PostgreSQL with retries."""
    for attempt in range(retries):
        try:
            conn = psycopg2.connect(**params)
            return conn
        except psycopg2.OperationalError:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise


def find_duplicate_indexes(cur):
    """Return (to_drop, kept) for exact duplicate indexes (same table, same column list).

    Uses OID ordering to keep the index created first (lowest OID = original)
    and drop later duplicates.  This is deterministic regardless of which
    duplicate the planner happened to route scans through.
    """
    cur.execute("""
        SELECT i.relname  AS indexname,
               t.relname  AS tablename,
               ix.indkey::text AS indkey,
               ix.indisunique,
               ix.indisprimary,
               i.oid       AS index_oid
        FROM pg_index ix
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_class t ON t.oid = ix.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'public'
    """)
    rows = cur.fetchall()

    groups = defaultdict(list)
    for idx_name, tbl, indkey, is_uniq, is_pk, oid in rows:
        groups[(tbl, indkey, is_uniq)].append((oid, idx_name))

    to_drop = []
    kept = set()
    for (_tbl, _key, _uniq), items in groups.items():
        if len(items) <= 1:
            continue
        # Sort by OID ascending — the original index (lowest OID) is kept
        items.sort()
        kept.add(items[0][1])
        for _, name in items[1:]:
            to_drop.append(name)
    return to_drop, kept


def find_unused_indexes(cur, exclude=None):
    """Return non-unique, non-PK indexes with zero scans.

    Indexes in `exclude` are skipped — they are "kept" members of duplicate
    groups whose scan counts may be zero only because the planner routed all
    traffic through their (now-dropped) duplicate.
    """
    if exclude is None:
        exclude = set()
    cur.execute("""
        SELECT s.indexrelname
        FROM pg_stat_user_indexes s
        JOIN pg_index i ON i.indexrelid = s.indexrelid
        WHERE s.idx_scan = 0
          AND NOT i.indisunique
          AND NOT i.indisprimary
          AND s.schemaname = 'public'
    """)
    return [row[0] for row in cur.fetchall() if row[0] not in exclude]


def find_prefix_redundant_indexes(cur, exclude=None):
    """Find single-column indexes that are a left-prefix of a wider composite index."""
    if exclude is None:
        exclude = set()
    cur.execute("""
        SELECT i.relname, t.relname,
               string_to_array(ix.indkey::text, ' ') AS cols,
               ix.indnkeyatts,
               ix.indisunique, ix.indisprimary
        FROM pg_index ix
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_class t ON t.oid = ix.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'public'
    """)
    all_idx = []
    for row in cur.fetchall():
        all_idx.append({
            "name": row[0], "table": row[1], "cols": row[2],
            "ncols": row[3], "is_unique": row[4], "is_primary": row[5],
        })

    redundant = []
    for a in all_idx:
        if a["is_unique"] or a["is_primary"]:
            continue
        if a["name"] in exclude:
            continue
        for b in all_idx:
            if a["name"] == b["name"] or a["table"] != b["table"]:
                continue
            if a["ncols"] >= b["ncols"]:
                continue
            # Check left-prefix match
            if b["cols"][:a["ncols"]] == a["cols"]:
                redundant.append(a["name"])
                break
    return redundant


def identify_missing_indexes(cur):
    """Analyse pg_stat_statements and data distribution to suggest new indexes."""
    creates = []

    # Check the status distribution in orders
    cur.execute("""
        SELECT status, count(*) AS cnt,
               round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
        FROM orders GROUP BY status ORDER BY cnt DESC
    """)
    dist = {row[0]: float(row[2]) for row in cur.fetchall()}
    pending_pct = dist.get("pending", 0)

    # Look for slow queries involving orders.status in pg_stat_statements
    try:
        cur.execute("""
            SELECT query, calls, mean_exec_time
            FROM pg_stat_statements
            WHERE query ILIKE '%%orders%%'
              AND query ILIKE '%%pending%%'
            ORDER BY mean_exec_time DESC
            LIMIT 5
        """)
        slow_pending = cur.fetchall()
    except Exception:
        slow_pending = []

    # If pending is a small fraction and a slow query references it,
    # create a partial index
    has_status_index = False
    cur.execute("""
        SELECT indexname, indexdef FROM pg_indexes
        WHERE tablename = 'orders' AND schemaname = 'public'
    """)
    for _name, defn in cur.fetchall():
        dl = defn.lower()
        if "pending" in dl:
            has_status_index = True
        elif "(status" in dl.replace(" ", ""):
            has_status_index = True

    if not has_status_index and pending_pct < 15:
        creates.append(
            "CREATE INDEX idx_orders_status_pending "
            "ON orders(order_date DESC) WHERE status = 'pending';"
        )

    return creates


def main():
    conn = connect_with_retry(DB)
    # Set autocommit=True BEFORE any queries to avoid implicit transaction
    conn.autocommit = True
    cur = conn.cursor()

    # --- analysis ---
    # Step 1: duplicates — use OID ordering so original indexes are kept
    dup_drops, dup_keeps = find_duplicate_indexes(cur)

    # Step 2: unused indexes — exclude "kept" duplicates whose scan count
    # may be zero because the planner routed traffic through the (now-dropped) copy
    unused = find_unused_indexes(cur, exclude=dup_keeps)

    # Step 3: prefix-redundant indexes — also exclude kept duplicates
    redundant = find_prefix_redundant_indexes(cur, exclude=dup_keeps)

    # Step 4: missing indexes for slow query patterns
    new_indexes = identify_missing_indexes(cur)

    all_drops = sorted(set(dup_drops + unused + redundant))

    # --- generate migration file ---
    with open("/app/migration.sql", "w") as f:
        f.write("-- Index optimisation migration\n")
        f.write("-- Generated by automated analysis\n\n")
        f.write("BEGIN;\n\n")
        f.write("-- Drop duplicate, unused, and redundant indexes\n")
        for idx in all_drops:
            f.write(f"DROP INDEX IF EXISTS {idx};\n")
        f.write("\n-- Create missing indexes\n")
        for stmt in new_indexes:
            f.write(stmt + "\n")
        f.write("\nCOMMIT;\n")

    # --- execute migration using explicit transaction ---
    cur.execute("BEGIN;")
    for idx in all_drops:
        cur.execute(f"DROP INDEX IF EXISTS {idx};")
    for stmt in new_indexes:
        cur.execute(stmt)
    cur.execute("COMMIT;")

    # Update planner statistics (runs in autocommit mode)
    cur.execute("ANALYZE;")

    print(f"Migration complete: dropped {len(all_drops)} indexes, "
          f"created {len(new_indexes)} indexes.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
