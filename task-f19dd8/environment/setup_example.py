#!/usr/bin/env python3
"""Create the example crash database and binary files for /app/examples/."""
import os
import sqlite3
import struct

os.makedirs("/app/examples", exist_ok=True)

# Create SQLite crash database
conn = sqlite3.connect("/app/examples/example.db")
with open("/app/schema.sql") as f:
    conn.executescript(f.read())

conn.execute("INSERT INTO crash_state VALUES ('master_record_lsn', '0')")

records = [
    (0, "BEGIN_CHECKPOINT", None, None, None, None),
    (1, "END_CHECKPOINT", None, None, None, None),
    (2, "UPDATE", 1, None, 10, None),
    (3, "COMMIT", 1, 2, None, None),
    (4, "UPDATE", 2, None, 20, None),
]
conn.executemany(
    "INSERT INTO wal_records VALUES (?, ?, ?, ?, ?, ?)", records
)
conn.commit()
conn.close()

# Create binary page state file (PGST format, no pages flushed)
with open("/app/examples/example.db.pgstate", "wb") as f:
    f.write(b"PGST")                    # magic
    f.write(struct.pack(">I", 0))        # entry count = 0
