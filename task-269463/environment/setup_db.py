#!/usr/bin/env python3
"""Creates the ECOMDB diagnostic environment with multi-format diagnostic data.

Data is distributed across:
- SQLite database: V$ view snapshots (sysstat, system_event, librarycache,
  sql_area, sql_plan_operations, sgastat), instance parameters, constraints
- Raw text alert log: /app/logs/alert_ecomdb.log
- CSV exports: /app/exports/db_cache_advice.csv, pga_target_advice.csv
"""

import sqlite3
import os
import csv

DB_PATH = "/app/ecomdb_diag.db"
ALERT_LOG_PATH = "/app/logs/alert_ecomdb.log"
EXPORTS_DIR = "/app/exports"


def create_schema(c):
    c.executescript("""
    CREATE TABLE snapshots (
        snap_id INTEGER PRIMARY KEY,
        description TEXT,
        begin_time TEXT,
        end_time TEXT
    );

    CREATE TABLE sysstat (
        snap_id INTEGER,
        statistic_id INTEGER,
        name TEXT,
        class INTEGER,
        value INTEGER
    );

    CREATE TABLE system_event (
        snap_id INTEGER,
        event TEXT,
        wait_class TEXT,
        total_waits INTEGER,
        total_timeouts INTEGER,
        time_waited_cs INTEGER,
        average_wait_cs REAL,
        time_waited_micro INTEGER
    );

    CREATE TABLE librarycache (
        snap_id INTEGER,
        namespace TEXT,
        gets INTEGER,
        gethits INTEGER,
        gethitratio REAL,
        pins INTEGER,
        pinhits INTEGER,
        pinhitratio REAL,
        reloads INTEGER,
        invalidations INTEGER
    );

    CREATE TABLE sql_area (
        snap_id INTEGER,
        sql_id TEXT,
        sql_text TEXT,
        executions INTEGER,
        buffer_gets INTEGER,
        disk_reads INTEGER,
        rows_processed INTEGER,
        elapsed_time INTEGER,
        cpu_time INTEGER,
        parse_calls INTEGER,
        first_load_time TEXT,
        module TEXT,
        action TEXT
    );

    CREATE TABLE sql_plan_operations (
        snap_id INTEGER,
        sql_id TEXT,
        plan_hash_value INTEGER,
        operation_id INTEGER,
        parent_id INTEGER,
        operation TEXT,
        options TEXT,
        object_name TEXT,
        object_type TEXT,
        rows_estimated INTEGER,
        bytes_estimated INTEGER,
        cost INTEGER,
        cpu_cost INTEGER,
        io_cost INTEGER,
        filter_predicates TEXT,
        access_predicates TEXT
    );

    CREATE TABLE sgastat (
        snap_id INTEGER,
        pool TEXT,
        name TEXT,
        bytes INTEGER
    );

    CREATE TABLE instance_parameters (
        snap_id INTEGER,
        name TEXT,
        value TEXT,
        isdefault TEXT,
        description TEXT
    );

    CREATE TABLE constraints (
        constraint_name TEXT PRIMARY KEY,
        constraint_value TEXT,
        description TEXT
    );
    """)


def populate_snapshots(c):
    c.execute("INSERT INTO snapshots VALUES (1, 'Baseline - normal weekday operations', '2024-11-11 08:00:00', '2024-11-11 20:00:00')")
    c.execute("INSERT INTO snapshots VALUES (2, 'Degraded - peak holiday traffic', '2024-11-15 00:00:00', '2024-11-15 12:00:00')")


def populate_sysstat(c):
    baseline = [
        (1, 0, "logons cumulative", 1, 142364),
        (1, 1, "logons current", 1, 123),
        (1, 5, "opened cursors cumulative", 1, 24146923),
        (1, 6, "opened cursors current", 1, 4236),
        (1, 7, "user commits", 1, 1423696),
        (1, 8, "user rollbacks", 1, 6423),
        (1, 9, "user calls", 1, 24146923),
        (1, 12, "recursive calls", 1, 42364692),
        (1, 19, "session logical reads", 1, 5350000000),
        (1, 25, "db block gets", 1, 850000013),
        (1, 26, "db block gets from cache", 1, 850000000),
        (1, 27, "db block gets from cache (fastpath)", 1, 800000000),
        (1, 38, "consistent gets", 1, 4500000013),
        (1, 39, "consistent gets from cache", 1, 4500000000),
        (1, 40, "consistent gets from cache (fastpath)", 1, 4200000000),
        (1, 48, "physical reads", 1, 200000163),
        (1, 49, "physical reads cache", 1, 200000000),
        (1, 50, "physical reads direct", 1, 163),
        (1, 51, "physical reads cache prefetch", 1, 120000),
        (1, 53, "physical read total bytes", 8, 1638400000000),
        (1, 55, "physical writes", 1, 142364923),
        (1, 60, "physical writes direct", 1, 6423),
        (1, 72, "physical read IO requests", 1, 200000000),
        (1, 74, "physical write IO requests", 1, 142364923),
        (1, 106, "parse count (total)", 64, 5000000),
        (1, 107, "parse count (hard)", 64, 400000),
        (1, 108, "parse count (failures)", 64, 2414),
        (1, 109, "parse count (describe)", 64, 63),
        (1, 116, "execute count", 64, 6419736),
        (1, 121, "sorts (memory)", 64, 3000000),
        (1, 122, "sorts (disk)", 64, 50000),
        (1, 123, "sorts (rows)", 64, 423646923),
        (1, 131, "table scans (short tables)", 64, 6419736),
        (1, 132, "table scans (long tables)", 64, 423646),
        (1, 133, "table scan rows gotten", 64, 24146923564),
        (1, 136, "table fetch by rowid", 64, 1923645923),
        (1, 140, "index fast full scans (full)", 64, 24146),
        (1, 141, "index fast full scans (rowid ranges)", 64, 6423),
        (1, 260, "redo size", 2, 24146923564),
        (1, 261, "redo entries", 2, 6423646),
        (1, 279, "redo log space requests", 2, 423),
        (1, 282, "redo writes", 2, 602923),
        (1, 284, "redo write time", 2, 301469),
        (1, 326, "session cursor cache hits", 64, 4800000),
        (1, 327, "session cursor cache count", 64, 244617),
        (1, 330, "cursor authentications", 64, 142364),
        (1, 331, "queries parallelized", 64, 0),
        (1, 339, "DDL statements parallelized", 64, 0),
        (1, 402, "DBWR checkpoints", 1, 423),
        (1, 403, "DBWR fusion writes", 1, 0),
    ]
    degraded = [
        (2, 0, "logons cumulative", 1, 284729),
        (2, 1, "logons current", 1, 247),
        (2, 5, "opened cursors cumulative", 1, 48293847),
        (2, 6, "opened cursors current", 1, 8472),
        (2, 7, "user commits", 1, 2847392),
        (2, 8, "user rollbacks", 1, 12847),
        (2, 9, "user calls", 1, 48293847),
        (2, 12, "recursive calls", 1, 84729384),
        (2, 19, "session logical reads", 1, 5474540976),
        (2, 25, "db block gets", 1, 892347142),
        (2, 26, "db block gets from cache", 1, 892347129),
        (2, 27, "db block gets from cache (fastpath)", 1, 847293847),
        (2, 38, "consistent gets", 1, 4582193860),
        (2, 39, "consistent gets from cache", 1, 4582193847),
        (2, 40, "consistent gets from cache (fastpath)", 1, 4293847291),
        (2, 48, "physical reads", 1, 847293347),
        (2, 49, "physical reads cache", 1, 847293184),
        (2, 50, "physical reads direct", 1, 163),
        (2, 51, "physical reads cache prefetch", 1, 389472),
        (2, 53, "physical read total bytes", 8, 6937165603328),
        (2, 55, "physical writes", 1, 284729847),
        (2, 60, "physical writes direct", 1, 12847),
        (2, 72, "physical read IO requests", 1, 847293184),
        (2, 74, "physical write IO requests", 1, 284729847),
        (2, 106, "parse count (total)", 64, 8472938),
        (2, 107, "parse count (hard)", 64, 3847291),
        (2, 108, "parse count (failures)", 64, 4829),
        (2, 109, "parse count (describe)", 64, 127),
        (2, 116, "execute count", 64, 12839472),
        (2, 121, "sorts (memory)", 64, 3847291),
        (2, 122, "sorts (disk)", 64, 489234),
        (2, 123, "sorts (rows)", 64, 847293847),
        (2, 131, "table scans (short tables)", 64, 12839472),
        (2, 132, "table scans (long tables)", 64, 847293),
        (2, 133, "table scan rows gotten", 64, 48293847129),
        (2, 136, "table fetch by rowid", 64, 3847291847),
        (2, 140, "index fast full scans (full)", 64, 48293),
        (2, 141, "index fast full scans (rowid ranges)", 64, 12847),
        (2, 260, "redo size", 2, 48293847129),
        (2, 261, "redo entries", 2, 12847293),
        (2, 279, "redo log space requests", 2, 847),
        (2, 282, "redo writes", 2, 1205847),
        (2, 284, "redo write time", 2, 602938),
        (2, 326, "session cursor cache hits", 64, 1203847),
        (2, 327, "session cursor cache count", 64, 489234),
        (2, 330, "cursor authentications", 64, 284729),
        (2, 331, "queries parallelized", 64, 0),
        (2, 339, "DDL statements parallelized", 64, 0),
        (2, 402, "DBWR checkpoints", 1, 847),
        (2, 403, "DBWR fusion writes", 1, 0),
    ]
    for s in baseline + degraded:
        c.execute("INSERT INTO sysstat VALUES (?,?,?,?,?)", s)


def populate_system_event(c):
    baseline = [
        (1, "SQL*Net message from client", "Idle", 24146923, 0, 4236469236, 175.38, 42364692360000),
        (1, "rdbms ipc message", "Idle", 6423646, 4236469, 2414692356, 375.92, 24146923560000),
        (1, "pmon timer", "Idle", 423646, 423645, 1423646923, 3360.47, 14236469230000),
        (1, "smon timer", "Idle", 142364, 142364, 923646923, 6488.28, 9236469230000),
        (1, "DIAG idle wait", "Idle", 423646, 423645, 423646923, 999.99, 4236469230000),
        (1, "db file sequential read", "User I/O", 1423696, 0, 4271, 3.0, 42710000),
        (1, "log file sync", "Commit", 602923, 0, 1809, 3.0, 18090000),
        (1, "db file scattered read", "User I/O", 120000, 0, 960, 8.0, 9600000),
        (1, "buffer busy waits", "Concurrency", 44612, 0, 223, 5.0, 2230000),
        (1, "enq: TX - row lock contention", "Application", 6369, 636, 318, 50.0, 3180000),
        (1, "latch: cache buffers chains", "Concurrency", 22256, 0, 111, 5.0, 1110000),
        (1, "free buffer waits", "Configuration", 4462, 0, 89, 20.0, 890000),
        (1, "latch: shared pool", "Concurrency", 11745, 0, 59, 5.0, 590000),
        (1, "log file parallel write", "System I/O", 602923, 0, 301, 0.5, 3010000),
        (1, "control file sequential read", "System I/O", 423646, 0, 212, 0.5, 2120000),
    ]
    degraded = [
        (2, "SQL*Net message from client", "Idle", 48293847, 0, 8472938472, 175.38, 84729384720000),
        (2, "rdbms ipc message", "Idle", 12847293, 8472938, 4829384712, 375.92, 48293847120000),
        (2, "pmon timer", "Idle", 847293, 847291, 2847293847, 3360.47, 28472938470000),
        (2, "smon timer", "Idle", 284729, 284729, 1847293847, 6488.28, 18472938470000),
        (2, "DIAG idle wait", "Idle", 847293, 847291, 847293847, 999.99, 8472938470000),
        (2, "Streams AQ: waiting for messages in the queue", "Idle", 489234, 489234, 489234847, 1000.0, 4892348470000),
        (2, "db file sequential read", "User I/O", 2847392, 0, 18493, 6.49, 184930000),
        (2, "enq: TX - row lock contention", "Application", 127394, 12847, 12739, 100.0, 127390000),
        (2, "buffer busy waits", "Concurrency", 892341, 0, 8923, 10.0, 89230000),
        (2, "db file scattered read", "User I/O", 389472, 0, 5842, 15.0, 58420000),
        (2, "log file sync", "Commit", 1205847, 0, 4221, 3.5, 42210000),
        (2, "latch: cache buffers chains", "Concurrency", 445120, 0, 2226, 5.0, 22260000),
        (2, "free buffer waits", "Configuration", 89234, 0, 1785, 20.0, 17850000),
        (2, "latch: shared pool", "Concurrency", 234891, 0, 1174, 5.0, 11740000),
        (2, "cursor: pin S wait on X", "Concurrency", 189472, 0, 947, 5.0, 9470000),
        (2, "library cache: mutex X", "Concurrency", 147293, 0, 736, 5.0, 7360000),
        (2, "log file parallel write", "System I/O", 1205847, 0, 602, 0.5, 6020000),
        (2, "db file parallel write", "System I/O", 284729, 0, 427, 1.5, 4270000),
        (2, "control file sequential read", "System I/O", 847293, 0, 423, 0.5, 4230000),
        (2, "control file parallel write", "System I/O", 127394, 0, 127, 1.0, 1270000),
        (2, "direct path read", "User I/O", 48293, 0, 96, 2.0, 960000),
        (2, "direct path write", "User I/O", 12847, 0, 25, 2.0, 250000),
        (2, "SQL*Net message to client", "Network", 48293847, 0, 482, 0.01, 4820000),
        (2, "SQL*Net more data from client", "Network", 284729, 0, 142, 0.5, 1420000),
    ]
    for e in baseline + degraded:
        c.execute("INSERT INTO system_event VALUES (?,?,?,?,?,?,?,?)", e)


def populate_librarycache(c):
    baseline = [
        (1, "SQL AREA", 4236469, 3847291, 0.908, 20000000, 19400000, 0.970, 14236, 4236),
        (1, "TABLE/PROCEDURE", 1923645, 1923463, 0.999, 10000000, 9990000, 0.999, 6, 0),
        (1, "BODY", 64236, 64155, 0.999, 8870, 8819, 0.994, 3, 0),
        (1, "TRIGGER", 24146, 24100, 0.998, 1852, 1844, 0.996, 0, 0),
        (1, "INDEX", 6423, 6420, 0.999, 29, 0, 0.0, 0, 0),
        (1, "CLUSTER", 2414, 2406, 0.997, 393, 380, 0.967, 0, 0),
        (1, "PIPE", 142364, 142356, 0.999, 55265, 55263, 1.0, 0, 0),
        (1, "OBJECT", 423, 419, 0.991, 0, 0, 0.0, 0, 0),
    ]
    degraded = [
        (2, "SQL AREA", 8472938, 5284729, 0.624, 21536413, 18520516, 0.860, 284729, 8472),
        (2, "TABLE/PROCEDURE", 3847291, 3842847, 0.999, 10775684, 10774401, 0.999, 12, 0),
        (2, "BODY", 128472, 128291, 0.999, 8870, 8819, 0.994, 3, 0),
        (2, "TRIGGER", 48293, 48201, 0.999, 1852, 1844, 0.996, 0, 0),
        (2, "INDEX", 12847, 12839, 0.999, 29, 0, 0.0, 0, 0),
        (2, "CLUSTER", 4829, 4812, 0.997, 393, 380, 0.967, 0, 0),
        (2, "PIPE", 284729, 284712, 0.999, 55265, 55263, 1.0, 0, 0),
        (2, "OBJECT", 847, 839, 0.991, 0, 0, 0.0, 0, 0),
    ]
    for row in baseline + degraded:
        c.execute("INSERT INTO librarycache VALUES (?,?,?,?,?,?,?,?,?,?)", row)


def populate_sgastat(c):
    rows = [
        (2, "shared pool", "free memory", 4829384),
        (2, "shared pool", "sql area", 184729384),
        (2, "shared pool", "library cache", 89472938),
        (2, "shared pool", "dictionary cache", 28472938),
        (2, "shared pool", "PL/SQL DIANA", 12847293),
        (2, "shared pool", "PL/SQL MPCODE", 8472938),
        (2, "shared pool", "KGH: NO ACCESS", 8472938),
        (2, "shared pool", "row cache", 4829384),
        (2, "shared pool", "KGLS heap", 2847293),
        (2, "shared pool", "kglsim object batch", 1847293),
        (2, "shared pool", "db_handles", 1284729),
        (2, "shared pool", "KQR L SO", 847293),
        (2, "shared pool", "KGLDA", 489234),
        (2, "shared pool", "event statistics per sess", 284729),
        (2, "shared pool", "kokc descriptor", 128472),
        (2, "large pool", "free memory", 12847293),
        (2, "large pool", "PX msg pool", 4829384),
        (2, "large pool", "RMAN buffers", 2847293),
        (2, "java pool", "free memory", 8472938),
        (2, "java pool", "joxs heap init", 4829384),
        (2, "buffer_cache", "DEFAULT", 268435456),
        (2, "log_buffer", "redo log buffer", 16777216),
        (2, "fixed_sga", "fixed sga", 2847293),
    ]
    for r in rows:
        c.execute("INSERT INTO sgastat VALUES (?,?,?,?)", r)


def populate_sql_area(c):
    rows = [
        (2, "f7k2m9x8n4p1q",
         "SELECT * FROM ORDERS WHERE ORDER_DATE BETWEEN :1 AND :2 AND CUSTOMER_ID = :3",
         284729, 847293184, 423847293, 284729, 48293847129, 28472938472, 284729,
         "2024-11-15/08:23:47", "JDBC Thin Client", None),
        (2, "a3b8c2d9e1f4g",
         "SELECT o.*, c.*, p.* FROM ORDERS o, CUSTOMERS c, PRODUCTS p WHERE o.ORDER_ID > :1",
         12847, 128472938, 84729384, 3847291, 12847293847, 8472938472, 12847,
         "2024-11-15/09:12:33", "JDBC Thin Client", None),
        (2, "h5j7k9l2m4n6p",
         "INSERT INTO ORDER_ITEMS (ORDER_ID, PRODUCT_ID, QTY, PRICE) VALUES (:1, :2, :3, :4)",
         1284729, 384729184, 2847293, 1284729, 8472938472, 4829384712, 1284729,
         "2024-11-14/00:00:01", "JDBC Thin Client", "batch_insert"),
        (2, "q8r1s3t5u7v9w",
         "UPDATE INVENTORY SET STOCK_LEVEL = STOCK_LEVEL - :1 WHERE PRODUCT_ID = :2",
         847293, 284729384, 84729384, 847293, 4829384712, 2847293847, 847293,
         "2024-11-14/00:00:01", "JDBC Thin Client", "inventory_update"),
        (2, "x2y4z6a8b1c3d",
         "SELECT COUNT(*) FROM ORDERS WHERE STATUS = :1 AND REGION_ID = :2",
         84729, 84729384, 42847293, 84729, 2847293847, 1847293847, 84729,
         "2024-11-15/10:45:22", "JDBC Thin Client", None),
        (2, "e5f7g9h2i4j6k",
         "SELECT product_name, list_price FROM PRODUCTS WHERE category_id = :1 ORDER BY list_price DESC",
         489234, 48293847, 4829384, 489234, 1284729384, 847293847, 489234,
         "2024-11-15/06:00:00", "JDBC Thin Client", None),
        (2, "m2n4p6q8r1s3t",
         "SELECT c.customer_name, SUM(o.total_amount) FROM CUSTOMERS c JOIN ORDERS o ON c.customer_id = o.customer_id WHERE o.order_date > :1 GROUP BY c.customer_name ORDER BY 2 DESC",
         4829, 4829384, 2847293, 4829, 847293847, 489234847, 4829,
         "2024-11-15/07:30:00", "JDBC Thin Client", "report"),
    ]
    for r in rows:
        c.execute("INSERT INTO sql_area VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", r)


def populate_sql_plan_operations(c):
    plan_f7k = [
        (2, "f7k2m9x8n4p1q", 3847291847, 0, None, "SELECT STATEMENT", None,
         None, None, 28473, 5767168, 84729, 42364500, 84729, None, None),
        (2, "f7k2m9x8n4p1q", 3847291847, 1, 0, "TABLE ACCESS", "FULL",
         "ORDERS", "TABLE", 28473, 5767168, 84729, 42364500, 84729,
         "ORDER_DATE>=:1 AND ORDER_DATE<=:2 AND CUSTOMER_ID=:3", None),
    ]
    plan_a3b = [
        (2, "a3b8c2d9e1f4g", 2847293847, 0, None, "SELECT STATEMENT", None,
         None, None, 847000000, 175006310400, 128472, 64236000, 128472, None, None),
        (2, "a3b8c2d9e1f4g", 2847293847, 1, 0, "MERGE JOIN", "CARTESIAN",
         None, None, 847000000, 175006310400, 128472, 64236000, 128472, None, None),
        (2, "a3b8c2d9e1f4g", 2847293847, 2, 1, "MERGE JOIN", "CARTESIAN",
         None, None, 284000000, 45942784000, 48293, 24146500, 48293, None, None),
        (2, "a3b8c2d9e1f4g", 2847293847, 3, 2, "TABLE ACCESS", "FULL",
         "ORDERS", "TABLE", 284000, 57917440, 84729, 42364500, 84729, "ORDER_ID>:1", None),
        (2, "a3b8c2d9e1f4g", 2847293847, 4, 2, "BUFFER", "SORT",
         None, None, 1000, 97000, 3, 1500, 3, None, None),
        (2, "a3b8c2d9e1f4g", 2847293847, 5, 4, "TABLE ACCESS", "FULL",
         "CUSTOMERS", "TABLE", 1000, 97000, 3, 1500, 3, None, None),
        (2, "a3b8c2d9e1f4g", 2847293847, 6, 1, "BUFFER", "SORT",
         None, None, 3000, 84000, 5, 2500, 5, None, None),
        (2, "a3b8c2d9e1f4g", 2847293847, 7, 6, "TABLE ACCESS", "FULL",
         "PRODUCTS", "TABLE", 3000, 84000, 5, 2500, 5, None, None),
    ]
    plan_x2y = [
        (2, "x2y4z6a8b1c3d", 1284729384, 0, None, "SELECT STATEMENT", None,
         None, None, 1, 12, 847, 423500, 847, None, None),
        (2, "x2y4z6a8b1c3d", 1284729384, 1, 0, "SORT", "AGGREGATE",
         None, None, 1, 12, None, None, None, None, None),
        (2, "x2y4z6a8b1c3d", 1284729384, 2, 1, "INDEX", "RANGE SCAN",
         "IDX_ORD_SR", "INDEX", 8473, 101676, 847, 423500, 847,
         None, "STATUS=:1 AND REGION_ID=:2"),
    ]
    plan_m2n = [
        (2, "m2n4p6q8r1s3t", 847293184, 0, None, "SELECT STATEMENT", None,
         None, None, 1000, 49152, 12847, 6423500, 12847, None, None),
        (2, "m2n4p6q8r1s3t", 847293184, 1, 0, "SORT", "ORDER BY",
         None, None, 1000, 49152, 12847, 6423500, 12847, None, None),
        (2, "m2n4p6q8r1s3t", 847293184, 2, 1, "HASH", "GROUP BY",
         None, None, 1000, 49152, 12847, 6423500, 12847, None, None),
        (2, "m2n4p6q8r1s3t", 847293184, 3, 2, "HASH JOIN", None,
         None, None, 284000, 14438400, 12840, 6420000, 12840,
         None, "C.CUSTOMER_ID=O.CUSTOMER_ID"),
        (2, "m2n4p6q8r1s3t", 847293184, 4, 3, "TABLE ACCESS", "FULL",
         "CUSTOMERS", "TABLE", 1000, 24576, 3, 1500, 3, None, None),
        (2, "m2n4p6q8r1s3t", 847293184, 5, 3, "TABLE ACCESS", "BY INDEX ROWID",
         "ORDERS", "TABLE", 284000, 7127040, 12837, 6418500, 12837,
         "NULL IS NOT NULL", None),
        (2, "m2n4p6q8r1s3t", 847293184, 6, 5, "INDEX", "RANGE SCAN",
         "IDX_ORD_DATE", "INDEX", 284000, None, 847, 423500, 847,
         None, "ORDER_DATE>:1"),
    ]
    for plan in plan_f7k + plan_a3b + plan_x2y + plan_m2n:
        c.execute("INSERT INTO sql_plan_operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", plan)


def populate_instance_parameters(c):
    rows = [
        (2, "db_cache_size", "268435456", "FALSE",
         "Size of DEFAULT buffer pool for standard block size buffers"),
        (2, "shared_pool_size", "335544320", "FALSE",
         "size in bytes of shared pool"),
        (2, "pga_aggregate_target", "201326592", "FALSE",
         "Target size for aggregate PGA memory"),
        (2, "pga_aggregate_limit", "402653184", "FALSE",
         "limit on aggregate PGA memory"),
        (2, "sga_target", "0", "TRUE", "Target size of SGA"),
        (2, "sga_max_size", "1073741824", "FALSE", "max total SGA size"),
        (2, "memory_target", "0", "TRUE",
         "Target size of Oracle Memory (SGA+PGA)"),
        (2, "memory_max_target", "0", "TRUE",
         "max size of Oracle Memory"),
        (2, "cursor_sharing", "EXACT", "TRUE",
         "cursor sharing mode"),
        (2, "optimizer_mode", "ALL_ROWS", "TRUE", "optimizer mode"),
        (2, "db_block_size", "8192", "FALSE",
         "Size of database block in bytes"),
        (2, "statistics_level", "TYPICAL", "TRUE", "statistics level"),
        (2, "result_cache_mode", "MANUAL", "TRUE",
         "result cache operator usage mode"),
        (2, "open_cursors", "300", "TRUE", "max cursors per session"),
        (2, "session_cached_cursors", "50", "TRUE",
         "Number of cursors to cache in a session"),
        (2, "log_buffer", "16777216", "FALSE",
         "redo circular buffer size"),
        (2, "processes", "300", "TRUE", "user processes"),
        (2, "db_writer_processes", "1", "TRUE",
         "number of background database writer processes"),
        (2, "compatible", "19.0.0", "FALSE",
         "Database compatibility version"),
        (2, "undo_management", "AUTO", "TRUE",
         "instance runs in SMU mode"),
        (2, "undo_retention", "900", "TRUE",
         "undo retention in seconds"),
        (2, "optimizer_adaptive_plans", "TRUE", "TRUE",
         "controls adaptive plans features"),
        (2, "optimizer_adaptive_statistics", "FALSE", "TRUE",
         "controls adaptive statistics features"),
    ]
    for r in rows:
        c.execute("INSERT INTO instance_parameters VALUES (?,?,?,?,?)", r)


def populate_constraints(c):
    rows = [
        ("max_sga_bytes", "1610612736",
         "Maximum total SGA memory budget (1.5GB). The sum of all SGA components must not exceed this value."),
        ("scope", "SPFILE",
         "All parameter changes must use SCOPE=SPFILE (requires restart). No SCOPE=BOTH or SCOPE=MEMORY."),
        ("no_application_changes", "true",
         "Remediation must not require application code changes."),
        ("current_sga_max_size", "1073741824",
         "Current sga_max_size setting. Adjust if recommended SGA exceeds this value."),
    ]
    for r in rows:
        c.execute("INSERT INTO constraints VALUES (?,?,?)", r)


def write_alert_log():
    """Write realistic Oracle 19c alert log from degraded period."""
    os.makedirs(os.path.dirname(ALERT_LOG_PATH), exist_ok=True)

    content = """\
Fri Nov 15 00:00:01 2024
Thread 1 advanced to log sequence 845 (LGWR switch)
Current log# 3 seq# 845 mem# 0: /u01/app/oracle/oradata/ECOMDB/redo03.log
Fri Nov 15 00:12:47 2024
Archived Log entry 844 added for thread 1 sequence 844 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 00:30:00 2024
Beginning global checkpoint up to RBA [0x34e.2.10], SCN: 0x0000000384729a
Fri Nov 15 00:45:18 2024
db_recovery_file_dest_size of 10737418240 bytes is 38.00% used. This is a
temporary condition, the DBA should take action to avoid exhaustion of the
recovery area.
Fri Nov 15 01:00:01 2024
Thread 1 advanced to log sequence 846 (LGWR switch)
Current log# 1 seq# 846 mem# 0: /u01/app/oracle/oradata/ECOMDB/redo01.log
Fri Nov 15 01:15:33 2024
Archived Log entry 845 added for thread 1 sequence 845 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 01:30:00 2024
Beginning global checkpoint up to RBA [0x352.1a4.10], SCN: 0x0000000385a21c
Fri Nov 15 01:45:12 2024
ALTER SYSTEM SET processes=300 SCOPE=SPFILE;
Fri Nov 15 02:00:01 2024
Thread 1 advanced to log sequence 847 (LGWR switch)
Current log# 2 seq# 847 mem# 0: /u01/app/oracle/oradata/ECOMDB/redo02.log
Fri Nov 15 02:15:33 2024
Errors in file /u01/app/oracle/diag/rdbms/ecomdb/ecomdb1/trace/ecomdb1_ora_28473.trc:
ORA-04031: unable to allocate 32784 bytes of shared memory ("shared pool","unknown object","sga heap(1,0)","kglsim object batch")
Additional information: 4829384 bytes of free memory in the shared pool
Fri Nov 15 02:30:00 2024
Beginning global checkpoint up to RBA [0x353.89.10], SCN: 0x00000003861bf4
Fri Nov 15 02:45:19 2024
Archived Log entry 846 added for thread 1 sequence 846 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 03:00:01 2024
Thread 1 advanced to log sequence 848 (LGWR switch)
Current log# 3 seq# 848 mem# 0: /u01/app/oracle/oradata/ECOMDB/redo03.log
Fri Nov 15 03:15:18 2024
Errors in file /u01/app/oracle/diag/rdbms/ecomdb/ecomdb1/trace/ecomdb1_ora_31947.trc:
ORA-00060: deadlock detected while waiting for resource
Deadlock graph:
                       ---------Blocker(s)---------  ---------Waiter(s)----------
Resource Name          process session holds waits   process session holds waits
TX-00190017-00002847   45      847     X             52      938           S
TX-0023001a-00003847   52      938     X             45      847           S
Rows waited on:
  Session 847: obj - rowid = 000038A1 - AAADihAAEAABt6PAAQ
  Session 938: obj - rowid = 000038A1 - AAADihAAEAABt6PAAR
Fri Nov 15 03:30:00 2024
Beginning global checkpoint up to RBA [0x354.1f2.10], SCN: 0x0000000387c4d2
Fri Nov 15 03:45:11 2024
Archived Log entry 847 added for thread 1 sequence 847 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 04:00:01 2024
Thread 1 advanced to log sequence 849 (LGWR switch)
Current log# 1 seq# 849 mem# 0: /u01/app/oracle/oradata/ECOMDB/redo01.log
Fri Nov 15 04:23:18 2024
Errors in file /u01/app/oracle/diag/rdbms/ecomdb/ecomdb1/trace/ecomdb1_ora_15283.trc:
ORA-04031: unable to allocate 65568 bytes of shared memory ("shared pool","SELECT * FROM ORDERS WHERE ORDER_DATE BETWEEN...","sga heap(1,0)","kglsim heap")
Additional information: 2847293 bytes of free memory in the shared pool
Fri Nov 15 04:30:00 2024
Beginning global checkpoint up to RBA [0x355.2c3.10], SCN: 0x0000000388e7a1
Fri Nov 15 04:45:22 2024
Archived Log entry 848 added for thread 1 sequence 848 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 05:00:01 2024
Thread 1 advanced to log sequence 850 (LGWR switch)
Current log# 2 seq# 850 mem# 0: /u01/app/oracle/oradata/ECOMDB/redo02.log
Fri Nov 15 05:15:47 2024
Errors in file /u01/app/oracle/diag/rdbms/ecomdb/ecomdb1/trace/ecomdb1_ora_22184.trc:
ORA-01555: snapshot too old: rollback segment number 7 with name "_SYSSMU7_2847293$" too small
Fri Nov 15 05:30:00 2024
Beginning global checkpoint up to RBA [0x356.3c1.10], SCN: 0x000000038a91e8
Fri Nov 15 05:45:33 2024
Archived Log entry 849 added for thread 1 sequence 849 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 06:00:01 2024
Thread 1 advanced to log sequence 851 (LGWR switch)
Current log# 3 seq# 851 mem# 0: /u01/app/oracle/oradata/ECOMDB/redo03.log
Fri Nov 15 06:15:09 2024
Archived Log entry 850 added for thread 1 sequence 850 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 06:30:00 2024
Beginning global checkpoint up to RBA [0x357.4d5.10], SCN: 0x000000038c3abf
Fri Nov 15 06:47:12 2024
Errors in file /u01/app/oracle/diag/rdbms/ecomdb/ecomdb1/trace/ecomdb1_ora_08472.trc:
ORA-04031: unable to allocate 16400 bytes of shared memory ("shared pool","unknown object","sga heap(1,0)","kglsim object batch")
Additional information: 1284729 bytes of free memory in the shared pool
Fri Nov 15 07:00:01 2024
Thread 1 advanced to log sequence 852 (LGWR switch)
Current log# 1 seq# 852 mem# 0: /u01/app/oracle/oradata/ECOMDB/redo01.log
Fri Nov 15 07:15:22 2024
Archived Log entry 851 added for thread 1 sequence 851 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 07:30:00 2024
Beginning global checkpoint up to RBA [0x358.5e6.10], SCN: 0x000000038de396
Fri Nov 15 07:30:22 2024
Resize operation completed for file# 4, fname /u01/app/oracle/oradata/ECOMDB/users01.dbf
Old size: 524288000, New size: 629145600
Fri Nov 15 08:00:01 2024
Thread 1 advanced to log sequence 853 (LGWR switch)
Current log# 2 seq# 853 mem# 0: /u01/app/oracle/oradata/ECOMDB/redo02.log
Fri Nov 15 08:15:44 2024
Archived Log entry 852 added for thread 1 sequence 852 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 08:30:00 2024
Beginning global checkpoint up to RBA [0x359.6f7.10], SCN: 0x000000038f8c6d
Fri Nov 15 08:34:55 2024
Errors in file /u01/app/oracle/diag/rdbms/ecomdb/ecomdb1/trace/ecomdb1_ora_19384.trc:
ORA-04031: unable to allocate 131104 bytes of shared memory ("shared pool","INSERT INTO AUDIT_LOG VALUES (:1,:2,:3,:4,:5,:6,:7,:8)","sga heap(2,0)","kglsim heap")
Additional information: 847293 bytes of free memory in the shared pool
Fri Nov 15 08:45:00 2024
Archived Log entry 852 added for thread 1 sequence 852 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 09:00:01 2024
Thread 1 advanced to log sequence 854 (LGWR switch)
Current log# 3 seq# 854 mem# 0: /u01/app/oracle/oradata/ECOMDB/redo03.log
Fri Nov 15 09:15:37 2024
Archived Log entry 853 added for thread 1 sequence 853 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 09:30:00 2024
Errors in file /u01/app/oracle/diag/rdbms/ecomdb/ecomdb1/trace/ecomdb1_ora_27381.trc:
ORA-01555: snapshot too old: rollback segment number 3 with name "_SYSSMU3_1847293$" too small
Fri Nov 15 09:45:19 2024
Archived Log entry 853 added for thread 1 sequence 853 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 10:00:01 2024
Thread 1 advanced to log sequence 855 (LGWR switch)
Current log# 1 seq# 855 mem# 0: /u01/app/oracle/oradata/ECOMDB/redo01.log
Fri Nov 15 10:15:28 2024
Archived Log entry 854 added for thread 1 sequence 854 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 10:30:00 2024
Beginning global checkpoint up to RBA [0x35b.808.10], SCN: 0x00000003912e44
Fri Nov 15 10:30:12 2024
Resize operation completed for file# 5, fname /u01/app/oracle/oradata/ECOMDB/temp01.dbf
Old size: 314572800, New size: 419430400
Fri Nov 15 10:45:33 2024
Archived Log entry 854 added for thread 1 sequence 854 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 11:00:01 2024
Thread 1 advanced to log sequence 856 (LGWR switch)
Current log# 2 seq# 856 mem# 0: /u01/app/oracle/oradata/ECOMDB/redo02.log
Fri Nov 15 11:15:41 2024
Archived Log entry 855 added for thread 1 sequence 855 ID 0xe8f3b2a1 dest 1:
Fri Nov 15 11:22:07 2024
Errors in file /u01/app/oracle/diag/rdbms/ecomdb/ecomdb1/trace/ecomdb1_ora_04738.trc:
ORA-04031: unable to allocate 49168 bytes of shared memory ("shared pool","unknown object","sga heap(1,0)","kglsim object batch")
Additional information: 489234 bytes of free memory in the shared pool
Fri Nov 15 11:30:00 2024
Beginning global checkpoint up to RBA [0x35c.919.10], SCN: 0x00000003929f1b
Fri Nov 15 11:45:00 2024
Archived Log entry 855 added for thread 1 sequence 855 ID 0xe8f3b2a1 dest 1:
"""
    with open(ALERT_LOG_PATH, "w") as f:
        f.write(content)


def write_csv_exports():
    """Write CSV exports of advisory views with multi-snapshot/multi-pool data."""
    os.makedirs(EXPORTS_DIR, exist_ok=True)

    # ---- db_cache_advice.csv ----
    cache_header = [
        "snap_id", "id", "name", "block_size", "advice_status",
        "size_for_estimate", "size_factor", "buffers_for_estimate",
        "estd_physical_read_factor", "estd_physical_reads",
        "estd_physical_read_time", "estd_pct_of_db_time_for_reads"
    ]
    cache_rows = [
        # Snap 1 baseline (healthy, less dramatic curve)
        [1, 1, "DEFAULT", 8192, "ON", 64, 0.25, 8192, 2.31, 462000000, 2847293, 4.3],
        [1, 1, "DEFAULT", 8192, "ON", 128, 0.50, 16384, 1.52, 304000000, 1847293, 2.8],
        [1, 1, "DEFAULT", 8192, "ON", 192, 0.75, 24576, 1.12, 224000000, 1384729, 2.1],
        [1, 1, "DEFAULT", 8192, "ON", 256, 1.00, 32768, 1.00, 200000000, 1284729, 1.9],
        [1, 1, "DEFAULT", 8192, "ON", 320, 1.25, 40960, 0.94, 188000000, 1184729, 1.8],
        [1, 1, "DEFAULT", 8192, "ON", 384, 1.50, 49152, 0.91, 182000000, 1124729, 1.7],
        [1, 1, "DEFAULT", 8192, "ON", 448, 1.75, 57344, 0.89, 178000000, 1084729, 1.6],
        # Snap 2 degraded DEFAULT pool (dramatic improvement curve)
        [2, 1, "DEFAULT", 8192, "ON", 64, 0.25, 8192, 5.42, 4592847391, 28472938, 42.8],
        [2, 1, "DEFAULT", 8192, "ON", 128, 0.50, 16384, 3.21, 2719384712, 16847293, 25.3],
        [2, 1, "DEFAULT", 8192, "ON", 192, 0.75, 24576, 1.89, 1601293847, 9847293, 14.8],
        [2, 1, "DEFAULT", 8192, "ON", 256, 1.00, 32768, 1.00, 847293184, 5284729, 7.9],
        [2, 1, "DEFAULT", 8192, "ON", 320, 1.25, 40960, 0.72, 610291093, 3847293, 5.8],
        [2, 1, "DEFAULT", 8192, "ON", 384, 1.50, 49152, 0.54, 457537919, 2847293, 4.3],
        [2, 1, "DEFAULT", 8192, "ON", 448, 1.75, 57344, 0.43, 364336069, 2284729, 3.4],
        [2, 1, "DEFAULT", 8192, "ON", 512, 2.00, 65536, 0.38, 321971810, 1984729, 3.0],
        [2, 1, "DEFAULT", 8192, "ON", 576, 2.25, 73728, 0.35, 296553614, 1847293, 2.8],
        [2, 1, "DEFAULT", 8192, "ON", 640, 2.50, 81920, 0.34, 288079282, 1784729, 2.7],
        [2, 1, "DEFAULT", 8192, "ON", 704, 2.75, 90112, 0.33, 283606750, 1747293, 2.6],
        [2, 1, "DEFAULT", 8192, "ON", 768, 3.00, 98304, 0.33, 279559350, 1724729, 2.6],
        # Snap 2 KEEP pool (noise — barely used)
        [2, 2, "KEEP", 8192, "ON", 16, 1.00, 2048, 1.00, 0, 0, 0.0],
        [2, 2, "KEEP", 8192, "ON", 32, 2.00, 4096, 1.00, 0, 0, 0.0],
        [2, 2, "KEEP", 8192, "ON", 48, 3.00, 6144, 1.00, 0, 0, 0.0],
        # Snap 2 RECYCLE pool (noise — barely used)
        [2, 3, "RECYCLE", 8192, "ON", 16, 1.00, 2048, 1.00, 0, 0, 0.0],
        [2, 3, "RECYCLE", 8192, "ON", 32, 2.00, 4096, 1.00, 0, 0, 0.0],
        [2, 3, "RECYCLE", 8192, "ON", 48, 3.00, 6144, 1.00, 0, 0, 0.0],
    ]
    with open(os.path.join(EXPORTS_DIR, "db_cache_advice.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cache_header)
        w.writerows(cache_rows)

    # ---- pga_target_advice.csv ----
    pga_header = [
        "snap_id", "pga_target_for_estimate", "pga_target_factor",
        "advice_status", "bytes_processed", "estd_extra_bytes_rw",
        "estd_pga_cache_hit_percentage", "estd_overalloc_count"
    ]
    pga_rows = [
        # Snap 1 baseline (healthy — no overalloc issues past 100MB)
        [1, 50331648, 0.25, "ON", 24146923564, 1284729384, 85, 24],
        [1, 100663296, 0.50, "ON", 24146923564, 284729384, 95, 0],
        [1, 150994944, 0.75, "ON", 24146923564, 84729384, 98, 0],
        [1, 201326592, 1.00, "ON", 24146923564, 28472938, 99, 0],
        [1, 251658240, 1.25, "ON", 24146923564, 8472938, 100, 0],
        [1, 301989888, 1.50, "ON", 24146923564, 2847293, 100, 0],
        # Snap 2 degraded (overalloc present up to 240MB)
        [2, 50331648, 0.25, "ON", 48293847129, 12847293847, 72, 847],
        [2, 100663296, 0.50, "ON", 48293847129, 4829384712, 89, 234],
        [2, 150994944, 0.75, "ON", 48293847129, 1847293847, 95, 45],
        [2, 201326592, 1.00, "ON", 48293847129, 847293184, 97, 12],
        [2, 251658240, 1.25, "ON", 48293847129, 284729384, 99, 0],
        [2, 301989888, 1.50, "ON", 48293847129, 84729318, 100, 0],
        [2, 402653184, 2.00, "ON", 48293847129, 8472931, 100, 0],
        [2, 603979776, 3.00, "ON", 48293847129, 847293, 100, 0],
        [2, 805306368, 4.00, "ON", 48293847129, 84729, 100, 0],
    ]
    with open(os.path.join(EXPORTS_DIR, "pga_target_advice.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(pga_header)
        w.writerows(pga_rows)


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    create_schema(c)
    populate_snapshots(c)
    populate_sysstat(c)
    populate_system_event(c)
    populate_librarycache(c)
    populate_sgastat(c)
    populate_sql_area(c)
    populate_sql_plan_operations(c)
    populate_instance_parameters(c)
    populate_constraints(c)

    conn.commit()
    conn.close()

    write_alert_log()
    write_csv_exports()

    print(f"Database created at {DB_PATH}")
    print(f"Alert log created at {ALERT_LOG_PATH}")
    print(f"CSV exports created in {EXPORTS_DIR}")


if __name__ == "__main__":
    main()
