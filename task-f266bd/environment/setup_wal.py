#!/usr/bin/env python3
"""Generate the WAL SQLite database for the crash recovery task."""

import sqlite3

conn = sqlite3.connect('/app/wal.db')
c = conn.cursor()

# Schema
c.execute('''CREATE TABLE log_records (
    lsn INTEGER PRIMARY KEY,
    record_type TEXT NOT NULL CHECK(record_type IN (
        'BEGIN','UPDATE','COMMIT','ABORT','END',
        'CHECKPOINT_BEGIN','CHECKPOINT_END','CLR','NTA_COMPLETE'
    )),
    txn_id INTEGER,
    page_id INTEGER,
    table_name TEXT,
    before_value INTEGER,
    after_value INTEGER,
    prev_lsn INTEGER,
    undo_next_lsn INTEGER,
    description TEXT
)''')

c.execute('''CREATE TABLE checkpoint_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checkpoint_lsn INTEGER NOT NULL,
    data_type TEXT NOT NULL CHECK(data_type IN ('DPT','TXN_TABLE')),
    entry_key INTEGER NOT NULL,
    rec_lsn INTEGER,
    status TEXT,
    last_lsn INTEGER
)''')

c.execute('''CREATE TABLE master_record (
    id INTEGER PRIMARY KEY DEFAULT 1,
    checkpoint_lsn INTEGER NOT NULL
)''')

c.execute('''CREATE VIEW transaction_summary AS
SELECT txn_id,
       MIN(lsn) as first_lsn,
       MAX(lsn) as last_lsn,
       COUNT(*) as record_count,
       GROUP_CONCAT(record_type, ', ') as record_sequence
FROM log_records
WHERE txn_id IS NOT NULL
GROUP BY txn_id
ORDER BY txn_id''')

c.execute('''CREATE VIEW page_operations AS
SELECT page_id,
       COUNT(*) as operation_count,
       MIN(lsn) as first_lsn,
       MAX(lsn) as last_lsn,
       GROUP_CONCAT(record_type || '(T' || txn_id || ')@' || lsn, ', ') as operations
FROM log_records
WHERE page_id IS NOT NULL
GROUP BY page_id
ORDER BY page_id''')

c.execute('''CREATE VIEW nta_records AS
SELECT lr.lsn, lr.txn_id, lr.undo_next_lsn,
       lr.prev_lsn as nta_last_op_lsn,
       lr.description
FROM log_records lr
WHERE lr.record_type = 'NTA_COMPLETE'
ORDER BY lr.lsn''')

# WAL records
records = [
    (10,  'BEGIN',    1, None, None,         None, None, None, None,
     'Transaction T1 begins - order placement'),
    (20,  'BEGIN',    2, None, None,         None, None, None, None,
     'Transaction T2 begins - order placement'),
    (30,  'UPDATE',  1, 1,    'orders',      0,    101,  10,   None,
     'T1 inserts order #101 for customer Alice'),
    (40,  'UPDATE',  1, 5,    'products',    100,  95,   30,   None,
     'T1 decrements stock for item Alpha (qty 5)'),
    (50,  'UPDATE',  2, 2,    'orders',      0,    201,  20,   None,
     'T2 inserts order #201 for customer Bob'),
    (60,  'UPDATE',  2, 6,    'products',    200,  190,  50,   None,
     'T2 decrements stock for item Beta (qty 10)'),
    (70,  'UPDATE',  2, 10,   'inv_index',   1000, 1090, 60,   None,
     'T2 updates inventory index node during B+ tree restructure (NTA operation)'),
    (80,  'NTA_COMPLETE', 2, None, None,     None, None, 70,   60,
     'T2 nested top action complete - index structural change is now durable regardless of T2 outcome'),
    (90,  'CHECKPOINT_BEGIN', None, None, None, None, None, None, None,
     'Fuzzy checkpoint initiated'),
    (100, 'CHECKPOINT_END',   None, None, None, None, None, None, None,
     'Checkpoint complete - DPT and transaction table snapshots stored in checkpoint_data table'),
    (110, 'UPDATE',  1, 7,    'order_items', 0,    701,  40,   None,
     'T1 inserts line item for order #101 (product Alpha, qty 5)'),
    (120, 'COMMIT',  1, None, None,          None, None, 110,  None,
     'Transaction T1 commits'),
    (130, 'END',     1, None, None,          None, None, 120,  None,
     'Transaction T1 complete'),
    (140, 'BEGIN',   3, None, None,          None, None, None, None,
     'Transaction T3 begins - price adjustment'),
    (150, 'UPDATE',  3, 3,    'orders',      0,    301,  140,  None,
     'T3 inserts order #301 for customer Carol'),
    (160, 'UPDATE',  2, 8,    'order_items', 0,    801,  80,   None,
     'T2 inserts line item for order #201 (product Beta, qty 10)'),
    (170, 'UPDATE',  3, 9,    'products',    50,   55,   150,  None,
     'T3 updates price for item Alpha ($50 -> $55)'),
    (180, 'BEGIN',   4, None, None,          None, None, None, None,
     'Transaction T4 begins - inventory adjustment'),
    (190, 'COMMIT',  3, None, None,          None, None, 170,  None,
     'Transaction T3 commits'),
    (200, 'END',     3, None, None,          None, None, 190,  None,
     'Transaction T3 complete'),
    (210, 'UPDATE',  4, 11,   'products',    300,  290,  180,  None,
     'T4 decrements stock for item Gamma (qty 10)'),
    (220, 'UPDATE',  4, 12,   'inv_index',   2000, 2290, 210,  None,
     'T4 updates inventory index node during B+ tree restructure (NTA operation)'),
    (230, 'NTA_COMPLETE', 4, None, None,     None, None, 220,  210,
     'T4 nested top action complete - index structural change is now durable regardless of T4 outcome'),
    (240, 'UPDATE',  2, 13,   'products',    500,  490,  160,  None,
     'T2 decrements stock for item Delta (qty 10)'),
    (250, 'UPDATE',  4, 14,   'products',    400,  380,  230,  None,
     'T4 decrements stock for item Epsilon (qty 20)'),
    # === CRASH 1 ===
    # === Recovery CLRs written during first recovery's undo ===
    (300, 'CLR',     4, 14,   'products',    380,  400,  250,  230,
     'CLR: undo T4 stock decrement on item Epsilon (restoring 400)'),
    (310, 'CLR',     2, 13,   'products',    490,  500,  240,  160,
     'CLR: undo T2 stock decrement on item Delta (restoring 500)'),
    (320, 'CLR',     4, 11,   'products',    290,  300,  300,  180,
     'CLR: undo T4 stock decrement on item Gamma (restoring 300)'),
    (330, 'END',     4, None, None,          None, None, 320,  None,
     'Transaction T4 complete (aborted and fully undone)'),
    # === CRASH 2 ===
]
c.executemany(
    'INSERT INTO log_records VALUES (?,?,?,?,?,?,?,?,?,?)', records)

# Checkpoint data (captured at CHECKPOINT_BEGIN LSN 90)
ckpt_dpt = [
    (100, 'DPT', 1,  30,   None, None),
    (100, 'DPT', 2,  50,   None, None),
    (100, 'DPT', 5,  40,   None, None),
    (100, 'DPT', 6,  60,   None, None),
    (100, 'DPT', 10, 70,   None, None),
]
ckpt_txn = [
    (100, 'TXN_TABLE', 1, None, 'RUNNING', 40),
    (100, 'TXN_TABLE', 2, None, 'RUNNING', 80),
]
for entry in ckpt_dpt + ckpt_txn:
    c.execute(
        'INSERT INTO checkpoint_data (checkpoint_lsn, data_type, entry_key, rec_lsn, status, last_lsn) '
        'VALUES (?,?,?,?,?,?)', entry)

# Master record
c.execute('INSERT INTO master_record VALUES (1, 90)')

conn.commit()
conn.close()
print("WAL database created at /app/wal.db")
