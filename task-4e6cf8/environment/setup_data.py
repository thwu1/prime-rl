#!/usr/bin/env python3
"""Generate test fixtures for SQLite WAL forensics task.

Creates a SQLite database in WAL mode with multiple transactions,
then corrupts the WAL at the first frame of transaction 4.
No answer files are written — tests verify independently.
"""

import sqlite3
import shutil
import struct
import os

DATA_DIR = '/app/data'
WORK_DIR = '/tmp/wal_setup'
WORK_DB = os.path.join(WORK_DIR, 'sensor_data.db')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)

conn = sqlite3.connect(WORK_DB)
conn.execute("PRAGMA page_size=4096")
conn.execute("PRAGMA journal_mode=wal")
conn.execute("PRAGMA wal_autocheckpoint=0")

conn.execute("""CREATE TABLE sensors (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT NOT NULL,
    reading REAL NOT NULL,
    ts INTEGER NOT NULL
)""")
conn.execute("CREATE INDEX idx_sensors_loc ON sensors(location)")
conn.commit()

# Checkpoint schema into main DB, truncate WAL
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

# Tx 1: Initial readings
conn.execute("INSERT INTO sensors VALUES (1,'temp_01','warehouse_a',22.5,1000)")
conn.execute("INSERT INTO sensors VALUES (2,'temp_02','warehouse_b',18.3,1000)")
conn.execute("INSERT INTO sensors VALUES (3,'humid_01','warehouse_a',45.0,1000)")
conn.commit()

# Tx 2: Update readings
conn.execute("UPDATE sensors SET reading=23.1, ts=2000 WHERE id=1")
conn.execute("UPDATE sensors SET reading=19.0, ts=2000 WHERE id=2")
conn.commit()

# Tx 3: New sensors
conn.execute("INSERT INTO sensors VALUES (4,'press_01','warehouse_c',1013.25,3000)")
conn.execute("INSERT INTO sensors VALUES (5,'temp_03','warehouse_c',21.0,3000)")
conn.commit()

# Tx 4: Mixed operations (will be corrupted)
conn.execute("DELETE FROM sensors WHERE id=3")
conn.execute("UPDATE sensors SET reading=24.5, ts=4000 WHERE id=1")
conn.execute("INSERT INTO sensors VALUES (6,'humid_02','warehouse_b',52.0,4000)")
conn.commit()

# Tx 5: Lab sensors
conn.execute("INSERT INTO sensors VALUES (7,'temp_04','lab_01',20.0,5000)")
conn.execute("INSERT INTO sensors VALUES (8,'press_02','lab_01',1015.0,5000)")
conn.commit()

# Copy files before connection close to preserve WAL
shutil.copy2(WORK_DB, os.path.join(DATA_DIR, 'sensor_data.db'))
shutil.copy2(WORK_DB + '-wal', os.path.join(DATA_DIR, 'sensor_data.db-wal'))

conn.close()

# --- Corrupt the WAL at the first frame of transaction 4 ---
wal_path = os.path.join(DATA_DIR, 'sensor_data.db-wal')
with open(wal_path, 'rb') as f:
    wal = bytearray(f.read())

page_size = struct.unpack('>I', wal[8:12])[0]
frame_hdr_size = 24
frame_size = frame_hdr_size + page_size
num_frames = (len(wal) - 32) // frame_size

# Find the commit frame for tx3 (3rd commit marker)
tx_num = 0
tx3_last_frame = None
for i in range(num_frames):
    offset = 32 + i * frame_size
    db_size = struct.unpack('>I', wal[offset + 4:offset + 8])[0]
    if db_size > 0:
        tx_num += 1
        if tx_num == 3:
            tx3_last_frame = i
            break

assert tx3_last_frame is not None, "Could not find tx3 commit frame"
corrupt_idx = tx3_last_frame + 1
assert corrupt_idx < num_frames, "No frame to corrupt after tx3"

# Corrupt page data (not header) to invalidate the frame checksum
byte_offset = 32 + corrupt_idx * frame_size + frame_hdr_size + 200
wal[byte_offset] ^= 0xFF
wal[byte_offset + 1] ^= 0xFF
wal[byte_offset + 2] ^= 0xFF
wal[byte_offset + 3] ^= 0xFF

with open(wal_path, 'wb') as f:
    f.write(wal)

# Clean up work directory
shutil.rmtree(WORK_DIR, ignore_errors=True)

print(f"Setup complete: {num_frames} frames, corrupted frame {corrupt_idx}")
