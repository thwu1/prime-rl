#!/usr/bin/env python3
"""
Create monitoring.db and incidents.db for the TiDB triage pipeline task.

"""
import sqlite3
import os

PLAN_DIR = "/app/data/plans"
DATA_DIR = "/app/data"


def create_monitoring_db():
    conn = sqlite3.connect(os.path.join(DATA_DIR, "monitoring.db"))
    c = conn.cursor()

    c.execute("""
        CREATE TABLE raw_plans (
            plan_id INTEGER PRIMARY KEY,
            source_label TEXT NOT NULL,
            plan_text TEXT NOT NULL,
            captured_at TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE system_config (
            variable_name TEXT PRIMARY KEY,
            variable_value TEXT NOT NULL
        )
    """)

    plans = [
        (1, "payments.uniq_acct_txn point lookup - latency spike investigation",
         "query_001.plan", "2025-06-10T14:23:07Z"),
        (2, "orders.idx_cust_name prefix scan - throughput analysis",
         "query_002.plan", "2025-06-10T14:25:31Z"),
        (3, "events.idx_ts MAX aggregate - performance baseline",
         "query_003a.plan", "2025-06-10T14:28:12Z"),
        (4, "events.idx_ts MIN aggregate - reported slowdown",
         "query_003b.plan", "2025-06-10T14:28:45Z"),
    ]

    for plan_id, label, filename, ts in plans:
        path = os.path.join(PLAN_DIR, filename)
        with open(path) as f:
            text = f.read()
        c.execute("INSERT INTO raw_plans VALUES (?, ?, ?, ?)",
                  (plan_id, label, text, ts))

    config_vars = [
        ("tidb_executor_concurrency", "8"),
        ("tidb_distsql_scan_concurrency", "20"),
        ("tidb_max_chunk_size", "1024"),
        ("tidb_index_lookup_size", "20000"),
        ("tidb_mem_quota_query", "1073741824"),
        ("gc_life_time", "10m0s"),
    ]
    for name, val in config_vars:
        c.execute("INSERT INTO system_config VALUES (?, ?)", (name, val))

    conn.commit()
    conn.close()


def create_incidents_db():
    conn = sqlite3.connect(os.path.join(DATA_DIR, "incidents.db"))
    c = conn.cursor()

    c.execute("""
        CREATE TABLE historical_incidents (
            id INTEGER PRIMARY KEY,
            query_pattern TEXT NOT NULL,
            operator_type TEXT NOT NULL,
            total_time_sec REAL NOT NULL,
            resolve_lock_time_ms REAL NOT NULL DEFAULT 0,
            backoff_count INTEGER NOT NULL DEFAULT 0,
            cop_tasks INTEGER NOT NULL DEFAULT 0,
            max_proc_keys INTEGER NOT NULL DEFAULT 0,
            scan_direction TEXT NOT NULL DEFAULT 'none',
            effective_concurrency INTEGER NOT NULL DEFAULT 1,
            configured_concurrency INTEGER NOT NULL DEFAULT 1,
            rpc_count INTEGER NOT NULL DEFAULT 0,
            verified_root_cause TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE remediations (
            id INTEGER PRIMARY KEY,
            incident_id INTEGER NOT NULL,
            strategy TEXT NOT NULL,
            actual_improvement_pct REAL NOT NULL,
            FOREIGN KEY (incident_id) REFERENCES historical_incidents(id)
        )
    """)

    # ── lock_contention incidents (IDs 1-8) ──
    lock_incidents = [
        (1, "SELECT * FROM orders WHERE order_id = ?",
         "point_get", 2.92, 2840.0, 12, 0, 5, "none", 1, 1, 7),
        (2, "SELECT balance FROM accounts WHERE acct_id = ?",
         "point_get", 4.25, 4120.0, 22, 0, 3, "none", 1, 1, 9),
        (3, "SELECT status FROM shipments WHERE tracking_id = ?",
         "point_get", 1.65, 1580.0, 9, 0, 8, "none", 1, 1, 5),
        (4, "SELECT * FROM users WHERE user_id = ? AND email = ?",
         "point_get", 3.42, 3350.0, 15, 0, 4, "none", 1, 1, 8),
        (5, "SELECT config FROM settings WHERE key = ?",
         "point_get", 0.95, 890.0, 8, 0, 2, "none", 1, 1, 4),
        (6, "SELECT * FROM inventory WHERE sku = ? FOR UPDATE",
         "point_get", 5.35, 5210.0, 28, 0, 6, "none", 1, 1, 11),
        (7, "SELECT payment_ref FROM transactions WHERE txn_id = ?",
         "point_get", 2.18, 2100.0, 11, 0, 3, "none", 1, 1, 6),
        (8, "SELECT metadata FROM sessions WHERE session_id = ?",
         "point_get", 1.50, 1420.0, 10, 0, 7, "none", 1, 1, 5),
    ]
    for row in lock_incidents:
        c.execute("""INSERT INTO historical_incidents
            (id, query_pattern, operator_type, total_time_sec,
             resolve_lock_time_ms, backoff_count, cop_tasks,
             max_proc_keys, scan_direction, effective_concurrency,
             configured_concurrency, rpc_count, verified_root_cause)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (*row, "lock_contention"))

    # ── mvcc_tombstone_scan incidents (IDs 9-15) ──
    mvcc_incidents = [
        (9, "SELECT MIN(created_at) FROM audit_log",
         "index_reader", 10.8, 0, 0, 185, 420000, "asc", 1, 1, 185),
        (10, "SELECT MIN(event_ts) FROM metrics_raw",
         "index_reader", 14.2, 0, 0, 240, 680000, "asc", 1, 1, 240),
        (11, "SELECT MIN(insert_time) FROM temp_records",
         "index_reader", 7.5, 0, 0, 92, 310000, "asc", 1, 1, 92),
        (12, "SELECT MIN(log_id) FROM access_logs",
         "index_reader", 18.9, 0, 0, 310, 890000, "asc", 1, 1, 310),
        (13, "SELECT MIN(timestamp) FROM sensor_data",
         "index_reader", 9.3, 0, 0, 150, 520000, "asc", 1, 1, 150),
        (14, "SELECT MIN(seq_no) FROM message_queue",
         "index_reader", 12.1, 0, 0, 205, 470000, "asc", 1, 1, 205),
        (15, "SELECT MIN(batch_id) FROM processing_jobs",
         "index_reader", 8.4, 0, 0, 128, 380000, "asc", 1, 1, 128),
    ]
    for row in mvcc_incidents:
        c.execute("""INSERT INTO historical_incidents
            (id, query_pattern, operator_type, total_time_sec,
             resolve_lock_time_ms, backoff_count, cop_tasks,
             max_proc_keys, scan_direction, effective_concurrency,
             configured_concurrency, rpc_count, verified_root_cause)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (*row, "mvcc_tombstone_scan"))

    # ── concurrency_bottleneck incidents (IDs 16-21) ──
    conc_incidents = [
        (16, "SELECT * FROM products WHERE category LIKE 'Electronics%'",
         "index_lookup", 0.045, 0, 0, 8, 2400, "none", 1, 8, 8),
        (17, "SELECT * FROM customers WHERE name LIKE 'Smith%'",
         "index_lookup", 0.062, 0, 0, 12, 3800, "none", 1, 5, 12),
        (18, "SELECT * FROM logs WHERE prefix = 'ERR'",
         "index_lookup", 0.028, 0, 0, 5, 1200, "none", 1, 8, 5),
        (19, "SELECT * FROM articles WHERE title LIKE 'Breaking%'",
         "index_lookup", 0.078, 0, 0, 15, 5200, "none", 1, 10, 15),
        (20, "SELECT * FROM tickets WHERE status LIKE 'OPEN%'",
         "index_lookup", 0.035, 0, 0, 6, 1800, "none", 1, 8, 6),
        (21, "SELECT * FROM records WHERE type_code LIKE 'A%'",
         "index_lookup", 0.042, 0, 0, 10, 2900, "none", 2, 8, 10),
    ]
    for row in conc_incidents:
        c.execute("""INSERT INTO historical_incidents
            (id, query_pattern, operator_type, total_time_sec,
             resolve_lock_time_ms, backoff_count, cop_tasks,
             max_proc_keys, scan_direction, effective_concurrency,
             configured_concurrency, rpc_count, verified_root_cause)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (*row, "concurrency_bottleneck"))

    # ── memory_pressure incidents (IDs 22-26) ──
    mem_incidents = [
        (22, "SELECT SUM(amount) FROM transactions GROUP BY region",
         "table_reader", 6.2, 0, 0, 45, 85000, "none", 8, 8, 45),
        (23, "SELECT COUNT(*) FROM orders JOIN items ON orders.id = items.order_id",
         "table_reader", 5.8, 0, 0, 38, 72000, "none", 5, 8, 38),
        (24, "SELECT a.*, b.* FROM large_table a JOIN dim_table b ON a.key = b.key",
         "hash_join", 8.4, 0, 0, 52, 95000, "none", 8, 8, 52),
        (25, "SELECT * FROM events WHERE event_date BETWEEN '2024-01-01' AND '2024-12-31'",
         "table_reader", 9.1, 0, 0, 60, 110000, "none", 8, 8, 60),
        (26, "SELECT customer_id, SUM(total) FROM invoices GROUP BY customer_id",
         "hash_join", 7.3, 0, 0, 42, 78000, "none", 8, 8, 42),
    ]
    for row in mem_incidents:
        c.execute("""INSERT INTO historical_incidents
            (id, query_pattern, operator_type, total_time_sec,
             resolve_lock_time_ms, backoff_count, cop_tasks,
             max_proc_keys, scan_direction, effective_concurrency,
             configured_concurrency, rpc_count, verified_root_cause)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (*row, "memory_pressure"))

    # ── network_latency incidents (IDs 27-30) ──
    net_incidents = [
        (27, "SELECT * FROM remote_catalog WHERE item_id IN (?, ?, ?)",
         "index_lookup", 1.2, 0, 0, 3, 450, "none", 5, 8, 3),
        (28, "SELECT config_value FROM global_settings WHERE key = ?",
         "point_get", 0.85, 0, 0, 0, 280, "none", 1, 1, 2),
        (29, "SELECT * FROM cross_dc_inventory WHERE warehouse_id = ?",
         "index_lookup", 1.8, 0, 0, 4, 620, "none", 8, 8, 4),
        (30, "SELECT * FROM replicated_users WHERE region = 'us-west'",
         "table_reader", 2.1, 0, 0, 5, 520, "none", 8, 8, 5),
    ]
    for row in net_incidents:
        c.execute("""INSERT INTO historical_incidents
            (id, query_pattern, operator_type, total_time_sec,
             resolve_lock_time_ms, backoff_count, cop_tasks,
             max_proc_keys, scan_direction, effective_concurrency,
             configured_concurrency, rpc_count, verified_root_cause)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (*row, "network_latency"))

    # ── Remediations ──

    remediation_data = [
        # lock_contention
        (1, 1, "reduce_transaction_scope", 68.0),
        (2, 2, "reduce_transaction_scope", 62.0),
        (3, 4, "reduce_transaction_scope", 71.0),
        (4, 6, "reduce_transaction_scope", 58.0),
        (5, 7, "reduce_transaction_scope", 65.0),
        (6, 1, "pessimistic_lock_timeout", 42.0),
        (7, 3, "pessimistic_lock_timeout", 48.0),
        (8, 5, "pessimistic_lock_timeout", 38.0),
        (9, 8, "pessimistic_lock_timeout", 52.0),
        (10, 2, "application_retry_backoff", 28.0),
        (11, 4, "application_retry_backoff", 35.0),
        (12, 6, "application_retry_backoff", 25.0),
        # mvcc_tombstone_scan
        (13, 9, "trigger_manual_gc", 88.0),
        (14, 10, "trigger_manual_gc", 82.0),
        (15, 12, "trigger_manual_gc", 92.0),
        (16, 14, "trigger_manual_gc", 78.0),
        (17, 9, "reduce_gc_lifetime", 72.0),
        (18, 11, "reduce_gc_lifetime", 68.0),
        (19, 13, "reduce_gc_lifetime", 75.0),
        (20, 15, "reduce_gc_lifetime", 65.0),
        (21, 10, "compaction_filter_enable", 55.0),
        (22, 12, "compaction_filter_enable", 62.0),
        (23, 14, "compaction_filter_enable", 48.0),
        # concurrency_bottleneck
        (24, 16, "increase_executor_concurrency", 65.0),
        (25, 17, "increase_executor_concurrency", 58.0),
        (26, 19, "increase_executor_concurrency", 72.0),
        (27, 21, "increase_executor_concurrency", 48.0),
        (28, 16, "add_covering_index", 52.0),
        (29, 18, "add_covering_index", 55.0),
        (30, 20, "add_covering_index", 42.0),
        (31, 17, "split_hot_region", 38.0),
        (32, 19, "split_hot_region", 32.0),
        (33, 21, "split_hot_region", 35.0),
        # memory_pressure
        (34, 22, "increase_mem_quota", 45.0),
        (35, 24, "increase_mem_quota", 50.0),
        (36, 26, "increase_mem_quota", 42.0),
        (37, 22, "enable_disk_spill", 55.0),
        (38, 23, "enable_disk_spill", 58.0),
        (39, 25, "enable_disk_spill", 62.0),
        (40, 23, "reduce_chunk_size", 30.0),
        (41, 25, "reduce_chunk_size", 28.0),
        (42, 26, "reduce_chunk_size", 35.0),
        # network_latency
        (43, 27, "colocate_placement", 72.0),
        (44, 29, "colocate_placement", 68.0),
        (45, 28, "batch_coprocessor", 45.0),
        (46, 30, "batch_coprocessor", 50.0),
        (47, 27, "reduce_rpc_count", 35.0),
        (48, 29, "reduce_rpc_count", 40.0),
        (49, 30, "reduce_rpc_count", 38.0),
    ]

    for rid, iid, strategy, pct in remediation_data:
        c.execute("INSERT INTO remediations VALUES (?, ?, ?, ?)",
                  (rid, iid, strategy, pct))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    create_monitoring_db()
    create_incidents_db()
    print("Databases created successfully.")
