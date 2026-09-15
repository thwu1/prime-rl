#!/usr/bin/env python3
"""Generate task data files for the hybrid vindex migration task."""
import json
import os
import random
import sqlite3

random.seed(42)

APP_DIR = "/app"
os.makedirs(APP_DIR, exist_ok=True)

# === Shard Configuration ===
NUM_SHARDS = 8
shard_config = {
    "keyspace": "etsy_commerce",
    "num_shards": NUM_SHARDS,
    "shard_ranges": [
        {"name": "-20", "start": "", "end": "20"},
        {"name": "20-40", "start": "20", "end": "40"},
        {"name": "40-60", "start": "40", "end": "60"},
        {"name": "60-80", "start": "60", "end": "80"},
        {"name": "80-a0", "start": "80", "end": "a0"},
        {"name": "a0-c0", "start": "a0", "end": "c0"},
        {"name": "c0-e0", "start": "c0", "end": "e0"},
        {"name": "e0-", "start": "e0", "end": ""},
    ],
}
with open(os.path.join(APP_DIR, "shard_config.json"), "w") as f:
    json.dump(shard_config, f, indent=2)

# === Table Configuration ===
tables = {
    "orders": {"shard_key": "shop_id", "threshold": 5000, "legacy_count": 5000},
    "order_items": {"shard_key": "shop_id", "threshold": 5000, "legacy_count": 5000},
    "payments": {"shard_key": "shop_id", "threshold": 5000, "legacy_count": 5000},
    "refunds": {"shard_key": "shop_id", "threshold": 3000, "legacy_count": 3000},
    "users": {"shard_key": "user_id", "threshold": 8000, "legacy_count": 8000},
    "user_addresses": {"shard_key": "user_id", "threshold": 8000, "legacy_count": 8000},
    "user_preferences": {"shard_key": "user_id", "threshold": 8000, "legacy_count": 8000},
    "listings": {"shard_key": "shop_id", "threshold": 6000, "legacy_count": 6000},
    "listing_images": {"shard_key": "shop_id", "threshold": 6000, "legacy_count": 6000},
    "listing_attributes": {"shard_key": "shop_id", "threshold": 6000, "legacy_count": 6000},
    "reviews": {"shard_key": "shop_id", "threshold": 6000, "legacy_count": 6000},
    "shops": {"shard_key": "shop_id", "threshold": 4000, "legacy_count": 4000},
    "shop_settings": {"shard_key": "shop_id", "threshold": 4000, "legacy_count": 4000},
    "analytics_events": {"shard_key": "user_id", "threshold": 10000, "legacy_count": 10000},
    "notifications": {"shard_key": "user_id", "threshold": 7000, "legacy_count": 7000},
}

with open(os.path.join(APP_DIR, "table_config.json"), "w") as f:
    json.dump(tables, f, indent=2)

# === Legacy Shard Mappings (SQLite) ===
db_path = os.path.join(APP_DIR, "legacy_mappings.db")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE shard_map (
        table_name TEXT NOT NULL,
        record_id INTEGER NOT NULL,
        shard_number INTEGER NOT NULL,
        PRIMARY KEY (table_name, record_id)
    )
""")
cursor.execute("CREATE INDEX idx_shard_map_table ON shard_map(table_name)")

for table_name, config in tables.items():
    rows = []
    for record_id in range(1, config["legacy_count"] + 1):
        shard_number = random.randint(0, NUM_SHARDS - 1)
        rows.append((table_name, record_id, shard_number))
    cursor.executemany(
        "INSERT INTO shard_map (table_name, record_id, shard_number) VALUES (?, ?, ?)",
        rows,
    )

conn.commit()
conn.close()

# === Transaction Log ===
# Coupling groups (tables written together in database transactions):
#   Group A: orders, order_items, payments, refunds
#   Group B: users, user_addresses, user_preferences
#   Group C: listings, listing_images, listing_attributes, reviews
#   Group D: shops, shop_settings
#   Singletons: analytics_events, notifications

coupling_groups = [
    ["orders", "order_items", "payments", "refunds"],
    ["users", "user_addresses", "user_preferences"],
    ["listings", "listing_images", "listing_attributes", "reviews"],
    ["shops", "shop_settings"],
]

transactions = []
txn_id = 0

# Multi-table transactions within each coupling group
for group in coupling_groups:
    for _ in range(200):
        num_tables = random.randint(2, len(group))
        selected = random.sample(group, num_tables)
        txn_id += 1
        transactions.append(
            {
                "txn_id": "txn_{:06d}".format(txn_id),
                "tables_written": sorted(selected),
                "shard_key_value": random.randint(1, 10000),
            }
        )

# Single-table transactions for uncoupled tables
for table in ["analytics_events", "notifications"]:
    for _ in range(100):
        txn_id += 1
        transactions.append(
            {
                "txn_id": "txn_{:06d}".format(txn_id),
                "tables_written": [table],
                "shard_key_value": random.randint(1, 10000),
            }
        )

# Single-table transactions from coupled groups (noise — does not create coupling)
for group in coupling_groups:
    for table in group:
        for _ in range(50):
            txn_id += 1
            transactions.append(
                {
                    "txn_id": "txn_{:06d}".format(txn_id),
                    "tables_written": [table],
                    "shard_key_value": random.randint(1, 10000),
                }
            )

random.shuffle(transactions)

with open(os.path.join(APP_DIR, "transaction_log.jsonl"), "w") as f:
    for txn in transactions:
        f.write(json.dumps(txn) + "\n")

# === Query Workload ===
queries = [
    # Targeted queries (shard key present in WHERE clause)
    {"query_id": "q001", "sql": "SELECT * FROM orders WHERE shop_id = ? AND order_date > '2024-01-01'", "table": "orders"},
    {"query_id": "q002", "sql": "SELECT * FROM users WHERE user_id = ?", "table": "users"},
    {"query_id": "q003", "sql": "SELECT * FROM listings WHERE shop_id = ? AND status = 'active'", "table": "listings"},
    {"query_id": "q004", "sql": "SELECT * FROM order_items WHERE shop_id = ? AND order_id = ?", "table": "order_items"},
    {"query_id": "q005", "sql": "SELECT * FROM payments WHERE shop_id = ? AND payment_status = 'completed'", "table": "payments"},
    {"query_id": "q006", "sql": "SELECT * FROM user_addresses WHERE user_id = ? AND is_default = 1", "table": "user_addresses"},
    {"query_id": "q007", "sql": "SELECT * FROM shops WHERE shop_id = ?", "table": "shops"},
    # Scatter queries (shard key missing from WHERE clause)
    {"query_id": "q008", "sql": "SELECT * FROM orders WHERE order_date > '2024-06-01'", "table": "orders"},
    {"query_id": "q009", "sql": "SELECT * FROM users WHERE email = 'user@example.com'", "table": "users"},
    {"query_id": "q010", "sql": "SELECT * FROM listings WHERE price < 10.00", "table": "listings"},
    {"query_id": "q011", "sql": "SELECT COUNT(*) FROM reviews WHERE rating >= 4", "table": "reviews"},
    {"query_id": "q012", "sql": "SELECT * FROM order_items WHERE product_sku = 'SKU-12345'", "table": "order_items"},
    {"query_id": "q013", "sql": "SELECT * FROM notifications WHERE created_at > '2024-01-01'", "table": "notifications"},
    {"query_id": "q014", "sql": "SELECT * FROM analytics_events WHERE event_type = 'page_view'", "table": "analytics_events"},
    {"query_id": "q015", "sql": "SELECT * FROM user_preferences WHERE theme = 'dark'", "table": "user_preferences"},
    {"query_id": "q016", "sql": "SELECT * FROM listing_images WHERE format = 'webp'", "table": "listing_images"},
    {"query_id": "q017", "sql": "SELECT * FROM payments WHERE amount > 1000", "table": "payments"},
    {"query_id": "q018", "sql": "SELECT * FROM refunds WHERE status = 'pending'", "table": "refunds"},
    {"query_id": "q019", "sql": "SELECT * FROM shop_settings WHERE currency = 'USD'", "table": "shop_settings"},
    {"query_id": "q020", "sql": "SELECT * FROM listing_attributes WHERE attribute_name = 'color'", "table": "listing_attributes"},
]

with open(os.path.join(APP_DIR, "query_workload.jsonl"), "w") as f:
    for q in queries:
        f.write(json.dumps(q) + "\n")

print("Setup complete. Data files generated in /app/")
