#!/usr/bin/env python3
"""Create the diagnostics SQLite database for the TiDB triage task."""
import sqlite3

DB_PATH = "/app/diagnostics.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("""
CREATE TABLE incidents (
    incident_id TEXT PRIMARY KEY,
    title TEXT,
    severity TEXT,
    reported_at TEXT,
    status TEXT
)
""")

c.executemany("INSERT INTO incidents VALUES (?, ?, ?, ?, ?)", [
    ("INC-001", "Point query latency spike on orders table", "P1",
     "2024-06-15 14:35:00", "open"),
    ("INC-002", "IndexLookUp concurrency analysis request", "P3",
     "2024-06-15 15:12:00", "open"),
    ("INC-003", "Asymmetric aggregate query performance on events table", "P2",
     "2024-06-15 15:48:00", "open"),
    ("INC-004", "Complex join query performance degradation", "P2",
     "2024-06-15 16:22:00", "open"),
])

c.execute("""
CREATE TABLE slow_queries (
    id INTEGER PRIMARY KEY,
    timestamp TEXT,
    query_text TEXT,
    query_digest TEXT,
    plan_digest TEXT,
    exec_time_ms REAL,
    process_time_ms REAL,
    plan_file TEXT,
    incident_id TEXT,
    tikv_store_addr TEXT,
    FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
)
""")

c.executemany("INSERT INTO slow_queries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
    (1, "2024-06-15 14:32:05",
     "select * from orders where order_id = 50421 and region = 'US-WEST'",
     "a3f8c21d9e7b4a6f", "plan_d1e2f3a4b5c6", 3200.0, 3180.0,
     "case1_lock_contention.planpb", "INC-001", "10.0.1.1:20160"),
    (2, "2024-06-15 14:33:12",
     "select count(*) from orders where status = 'pending'",
     "b7e4d2c1a9f8e3d2", "plan_a1b2c3d4e5f6", 1250.0, 1200.0,
     None, None, "10.0.1.2:20160"),
    (3, "2024-06-15 14:35:45",
     "update inventory set quantity = quantity - 1 where sku = '12345'",
     "c2d3e4f5a6b7c8d9", "plan_f6e5d4c3b2a1", 890.0, 850.0,
     None, None, "10.0.1.3:20160"),
    (4, "2024-06-15 15:10:22",
     "select * from inventory where sku like '98712%'",
     "d9e8f7a6b5c4d3e2", "plan_g1h2i3j4k5l6", 4.21, 3.8,
     "case2_concurrency.planpb", "INC-002", "10.0.1.1:20160"),
    (5, "2024-06-15 15:15:30",
     "select * from customers where email like '%@example.com'",
     "e1f2a3b4c5d6e7f8", "plan_m1n2o3p4q5r6", 2100.0, 2000.0,
     None, None, "10.0.1.2:20160"),
    (6, "2024-06-15 15:45:33",
     "select max(created_at) from events limit 1",
     "f8a7b6c5d4e3f2a1", "plan_s1t2u3v4w5x6", 3.542, 3.41,
     "case3_max.planpb", "INC-003", "10.0.1.1:20160"),
    (7, "2024-06-15 15:45:38",
     "select min(created_at) from events limit 1",
     "a1b7c6d5e4f3a2b1", "plan_y1z2a3b4c5d6", 9514.0, 9500.0,
     "case3_min.planpb", "INC-003", "10.0.1.3:20160"),
    (8, "2024-06-15 15:50:00",
     "select avg(total) from orders where created_at > '2024-01-01'",
     "g2h3i4j5k6l7m8n9", "plan_e1f2g3h4i5j6", 3500.0, 3400.0,
     None, None, "10.0.1.1:20160"),
    (9, "2024-06-15 16:00:15",
     "delete from sessions where expired_at < '2024-06-14'",
     "o1p2q3r4s5t6u7v8", "plan_k1l2m3n4o5p6", 4200.0, 4100.0,
     None, None, "10.0.1.2:20160"),
    (10, "2024-06-15 16:20:11",
     "select o.order_id, o.total, c.name from orders o join customers c "
     "on o.customer_id = c.id where o.created_at > '2024-01-01' "
     "and c.tier = 'premium'",
     "c3d4e5f6a7b8c9d0", "plan_q1r2s3t4u5v6", 285.0, 280.0,
     "case4_complex_join.planpb", "INC-004", "10.0.1.1:20160"),
    (11, "2024-06-15 16:25:00",
     "insert into audit_log select * from temp_audit",
     "w1x2y3z4a5b6c7d8", "plan_w1x2y3z4a5b6", 5600.0, 5500.0,
     None, None, "10.0.1.3:20160"),
    (12, "2024-06-15 16:30:22",
     "select * from products where category_id in "
     "(select id from categories where active = 1)",
     "e5f6g7h8i9j0k1l2", "plan_c1d2e3f4g5h6", 1800.0, 1700.0,
     None, None, "10.0.1.2:20160"),
])

c.execute("""
CREATE TABLE tidb_variables (
    variable_name TEXT PRIMARY KEY,
    variable_value TEXT,
    scope TEXT
)
""")

c.executemany("INSERT INTO tidb_variables VALUES (?, ?, ?)", [
    ("tidb_executor_concurrency", "5", "global"),
    ("tidb_distsql_scan_concurrency", "15", "global"),
    ("tikv_gc_life_time", "10m0s", "global"),
    ("tidb_max_chunk_size", "1024", "global"),
    ("tidb_mem_quota_query", "1073741824", "global"),
    ("tidb_index_lookup_concurrency", "5", "global"),
    ("tidb_index_lookup_size", "20000", "global"),
    ("tidb_hash_join_concurrency", "5", "global"),
    ("tidb_opt_agg_push_down", "0", "global"),
    ("tidb_opt_write_row_id", "0", "global"),
    ("tidb_build_stats_concurrency", "4", "global"),
    ("tidb_checksum_table_concurrency", "4", "global"),
    ("tidb_enable_streaming", "0", "global"),
    ("tidb_retry_limit", "10", "global"),
    ("tidb_backoff_lock_fast", "100", "global"),
    ("tidb_ddl_reorg_batch_size", "256", "global"),
    ("tidb_opt_correlation_threshold", "0.9", "global"),
    ("tidb_opt_correlation_exp_factor", "1", "global"),
    ("tidb_enable_window_function", "1", "global"),
    ("tidb_enable_vectorized_expression", "1", "global"),
    ("tidb_enable_cascades_planner", "0", "global"),
    ("tidb_isolation_read_engines", "tikv,tiflash,tidb", "global"),
    ("tidb_store_limit", "0", "global"),
    ("tidb_metric_query_step", "60", "global"),
    ("tidb_metric_query_range_duration", "60", "global"),
    ("tidb_enable_collect_execution_info", "1", "global"),
    ("tidb_enable_telemetry", "0", "global"),
    ("tidb_enable_amend_pessimistic_txn", "0", "global"),
    ("tidb_max_delta_schema_count", "1024", "global"),
    ("tidb_scatter_region", "0", "global"),
])

c.execute("""
CREATE TABLE tikv_stores (
    store_id INTEGER PRIMARY KEY,
    address TEXT,
    state TEXT,
    region_count INTEGER,
    leader_count INTEGER,
    storage_used_gb REAL,
    storage_available_gb REAL,
    uptime_hours REAL
)
""")

c.executemany("INSERT INTO tikv_stores VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
    (1, "10.0.1.1:20160", "Up", 8542, 8102, 3.82, 0.42, 2184.5),
    (2, "10.0.1.2:20160", "Up", 8721, 7856, 3.91, 0.33, 2184.5),
    (3, "10.0.1.3:20160", "Up", 8398, 8245, 3.75, 0.49, 2184.5),
])

c.execute("""
CREATE TABLE gc_history (
    id INTEGER PRIMARY KEY,
    run_time TEXT,
    safe_point TEXT,
    duration_sec REAL,
    keys_processed INTEGER,
    tombstone_cleaned INTEGER,
    status TEXT
)
""")

c.executemany("INSERT INTO gc_history VALUES (?, ?, ?, ?, ?, ?, ?)", [
    (1, "2024-06-15 14:00:00", "438742159231623170",
     421.3, 1823456, 892341, "success"),
    (2, "2024-06-14 14:00:00", "438738567891234560",
     385.7, 1652341, 734521, "success"),
    (3, "2024-06-13 14:00:00", "438734976551845750",
     412.1, 1745632, 812345, "success"),
])

conn.commit()
conn.close()
