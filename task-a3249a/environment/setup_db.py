#!/usr/bin/env python3
"""Set up a SQLite database in WAL mode with multiple un-checkpointed transactions."""
import sqlite3
import shutil
import os

TMP_PATH = '/tmp/forensic_setup.db'
FINAL_DB = '/app/forensic.db'
FINAL_WAL = '/app/forensic.db-wal'

# Clean up any leftovers
for f in [TMP_PATH, TMP_PATH + '-wal', TMP_PATH + '-shm',
          FINAL_DB, FINAL_WAL, FINAL_DB + '-shm']:
    try:
        os.remove(f)
    except FileNotFoundError:
        pass

# Use isolation_level=None (autocommit) so we control transactions explicitly.
# Python's default isolation_level implicitly commits before DDL statements,
# which would split CREATE TABLE into its own transaction.
conn = sqlite3.connect(TMP_PATH, isolation_level=None)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA wal_autocheckpoint=0')

# Transaction 1: Create table and seed data
conn.execute('BEGIN')
conn.execute('''CREATE TABLE sensors (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    status TEXT NOT NULL
)''')
conn.execute("INSERT INTO sensors VALUES (1, 'temp_north', 22.5, 'active')")
conn.execute("INSERT INTO sensors VALUES (2, 'temp_south', 24.1, 'active')")
conn.execute("INSERT INTO sensors VALUES (3, 'humidity', 65.0, 'active')")
conn.execute('COMMIT')

# Transaction 2: Update readings, add sensor
conn.execute('BEGIN')
conn.execute("UPDATE sensors SET value = 23.1 WHERE id = 1")
conn.execute("UPDATE sensors SET value = 25.0 WHERE id = 2")
conn.execute("INSERT INTO sensors VALUES (4, 'pressure', 1013.25, 'active')")
conn.execute('COMMIT')

# Transaction 3: Sensor failure + updated reading + new sensor
conn.execute('BEGIN')
conn.execute("UPDATE sensors SET status = 'failed', value = -1.0 WHERE id = 3")
conn.execute("UPDATE sensors SET value = 22.8 WHERE id = 1")
conn.execute("INSERT INTO sensors VALUES (5, 'wind_speed', 12.5, 'active')")
conn.execute('COMMIT')

# Transaction 4: Recovery, cleanup, new sensors
conn.execute('BEGIN')
conn.execute("UPDATE sensors SET value = 24.5 WHERE id = 2")
conn.execute("UPDATE sensors SET value = 67.0, status = 'recovered' WHERE id = 3")
conn.execute("DELETE FROM sensors WHERE id = 5")
conn.execute("INSERT INTO sensors VALUES (6, 'co2', 412.5, 'active')")
conn.execute("INSERT INTO sensors VALUES (7, 'light', 850.0, 'active')")
conn.execute('COMMIT')

# Copy DB and WAL before closing the connection.
# Closing the connection triggers a passive checkpoint which would
# merge WAL frames back into the main database and delete the WAL file.
# We need the WAL preserved for the forensics task.
shutil.copy2(TMP_PATH, FINAL_DB)
shutil.copy2(TMP_PATH + '-wal', FINAL_WAL)

conn.close()

# Verify
assert os.path.exists(FINAL_DB), "Database file not created"
assert os.path.exists(FINAL_WAL), "WAL file not created"
assert os.path.getsize(FINAL_WAL) > 32, "WAL file too small (no frames)"
print(f"Setup complete. DB: {os.path.getsize(FINAL_DB)} bytes, "
      f"WAL: {os.path.getsize(FINAL_WAL)} bytes")
