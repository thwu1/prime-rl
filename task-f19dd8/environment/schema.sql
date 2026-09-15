-- Crash scenario database schema
-- Each database represents the state captured at the moment of a crash
-- Note: flushed page state is in the companion .pgstate binary file, not here

CREATE TABLE wal_records (
    lsn INTEGER PRIMARY KEY,
    record_type TEXT NOT NULL CHECK (record_type IN (
        'UPDATE', 'CLR', 'COMMIT', 'ABORT', 'END',
        'BEGIN_CHECKPOINT', 'END_CHECKPOINT'
    )),
    txn_id INTEGER,
    prev_lsn INTEGER,
    page_id INTEGER,
    undo_next_lsn INTEGER
);

CREATE TABLE crash_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE checkpoint_txn_snapshot (
    checkpoint_lsn INTEGER NOT NULL,
    txn_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    last_lsn INTEGER NOT NULL,
    PRIMARY KEY (checkpoint_lsn, txn_id),
    FOREIGN KEY (checkpoint_lsn) REFERENCES wal_records(lsn)
);

CREATE TABLE checkpoint_dpt_snapshot (
    checkpoint_lsn INTEGER NOT NULL,
    page_id INTEGER NOT NULL,
    rec_lsn INTEGER NOT NULL,
    PRIMARY KEY (checkpoint_lsn, page_id),
    FOREIGN KEY (checkpoint_lsn) REFERENCES wal_records(lsn)
);
