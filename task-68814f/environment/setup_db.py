#!/usr/bin/env python3
"""
Generate the SIMDB crash-recovery scenario.

Creates:
  /app/data.db        - Database file with deliberate corruption
  /app/wal.log        - WAL with interleaved, mixed-status transactions
  /app/backup.sqlite  - SQLite backup of the pre-WAL database state
"""
import os
import sqlite3
import struct
import zlib

PAGE_SIZE = 4096
HEADER_SIZE = 32

BEGIN = 1
PAGE_WRITE = 2
COMMIT = 3
ABORT = 4


def encode_page(entries):
    """Encode entries into a binary page, sorted by key."""
    sorted_entries = sorted(entries, key=lambda x: x[0])
    data = struct.pack('>H', len(sorted_entries))
    for key, value in sorted_entries:
        kb = key.encode('utf-8')
        vb = value.encode('utf-8')
        data += struct.pack('>HH', len(kb), len(vb)) + kb + vb
    assert len(data) <= PAGE_SIZE
    return data + b'\x00' * (PAGE_SIZE - len(data))


def pages_checksum(pages):
    return zlib.crc32(b''.join(pages)) & 0xFFFFFFFF


def write_db(filepath, pages):
    cksum = pages_checksum(pages)
    hdr = struct.pack('>6sHIII', b'SIMDB\x00', 1, PAGE_SIZE,
                      len(pages), cksum)
    hdr += b'\x00' * (HEADER_SIZE - len(hdr))
    with open(filepath, 'wb') as f:
        f.write(hdr)
        for p in pages:
            f.write(p)


def make_frame(ft, txn_id, page_num=None, page_data=None,
               corrupt_crc=False):
    body = struct.pack('>BI', ft, txn_id)
    if ft == PAGE_WRITE:
        body += struct.pack('>I', page_num) + page_data
    crc = zlib.crc32(body) & 0xFFFFFFFF
    if corrupt_crc:
        crc ^= 0xDEADBEEF
    frame_len = len(body) + 4
    return struct.pack('>I', frame_len) + body + struct.pack('>I', crc)


def write_wal(filepath, db_checksum, frames, truncate_last=False):
    hdr = struct.pack('>8sHI', b'SIMWAL\x00\x00', 1, db_checksum)
    hdr += b'\x00' * (32 - len(hdr))
    with open(filepath, 'wb') as f:
        f.write(hdr)
        for i, frame in enumerate(frames):
            if truncate_last and i == len(frames) - 1:
                f.write(frame[:len(frame) // 2])
            else:
                f.write(frame)


def create_sqlite_backup(filepath, all_page_entries, initial_pages):
    if os.path.exists(filepath):
        os.remove(filepath)
    conn = sqlite3.connect(filepath)
    cur = conn.cursor()

    # -- Core tables ---------------------------------------------------
    cur.execute('''CREATE TABLE kv_snapshot (
        page_num  INTEGER NOT NULL,
        key       TEXT    NOT NULL,
        value     TEXT    NOT NULL,
        PRIMARY KEY (page_num, key)
    )''')
    cur.execute('''CREATE TABLE db_config (
        param TEXT PRIMARY KEY,
        val   TEXT NOT NULL
    )''')
    cur.execute("INSERT INTO db_config VALUES ('page_size', ?)",
                (str(PAGE_SIZE),))
    cur.execute("INSERT INTO db_config VALUES ('page_count', ?)",
                (str(len(all_page_entries)),))
    cur.execute("INSERT INTO db_config VALUES ('format_version', '1')")

    for page_num, entries in enumerate(all_page_entries):
        for key, value in entries:
            cur.execute(
                'INSERT INTO kv_snapshot (page_num, key, value) '
                'VALUES (?, ?, ?)',
                (page_num, key, value))

    # -- WAL metadata (from pre-crash monitoring -- PARTIALLY WRONG) ---
    cur.execute('''CREATE TABLE wal_metadata (
        txn_id           INTEGER PRIMARY KEY,
        observed_status  TEXT NOT NULL,
        monitor_timestamp TEXT,
        note             TEXT
    )''')
    wal_meta = [
        (1001, 'committed',   '2024-01-15T10:35:00Z', None),
        (1002, 'committed',   '2024-01-15T10:35:01Z', 'auto-detected'),
        (1003, 'committed',   '2024-01-15T10:35:02Z', None),
        (1004, 'committed',   '2024-01-15T10:35:03Z', 'retry pending'),
        (1005, 'in_progress', '2024-01-15T10:35:04Z', 'crc warning'),
        (1006, 'committed',   '2024-01-15T10:35:05Z', None),
        (1007, 'in_progress', '2024-01-15T10:35:06Z', 'incomplete'),
    ]
    for txn_id, status, ts, note in wal_meta:
        cur.execute(
            'INSERT INTO wal_metadata VALUES (?, ?, ?, ?)',
            (txn_id, status, ts, note))

    # -- Per-page checksums (pre-WAL state) ----------------------------
    cur.execute('''CREATE TABLE page_checksums (
        page_num     INTEGER PRIMARY KEY,
        checksum_hex TEXT NOT NULL
    )''')
    for page_num, page_bytes in enumerate(initial_pages):
        cksum = zlib.crc32(page_bytes) & 0xFFFFFFFF
        cur.execute("INSERT INTO page_checksums VALUES (?, ?)",
                    (page_num, f"0x{cksum:08X}"))

    conn.commit()
    conn.close()


# --- Initial database pages (6 pages) --------------------------------

page0_entries = [
    ("config:version",    "1.0.0"),
    ("config:name",       "testdb"),
    ("config:created_at", "2024-01-15T10:30:00Z"),
]
page1_entries = [
    ("user:1:name",  "Alice"),
    ("user:1:email", "alice@example.com"),
    ("user:2:name",  "Bob"),
    ("user:2:email", "bob@example.com"),
]
page2_entries = [
    ("counter:visits",  "42"),
    ("counter:errors",  "7"),
    ("counter:signups", "15"),
]
page3_entries = [
    ("session:abc123", "user:1"),
    ("session:def456", "user:2"),
]
page4_entries = [
    ("perm:admin:read",  "true"),
    ("perm:admin:write", "true"),
    ("perm:user:read",   "true"),
    ("perm:user:write",  "false"),
]
page5_entries = [
    ("audit:001:action",    "create_user"),
    ("audit:001:target",    "user:1"),
    ("audit:001:timestamp", "2024-01-15T10:31:00Z"),
    ("audit:002:action",    "create_user"),
    ("audit:002:target",    "user:2"),
    ("audit:002:timestamp", "2024-01-15T10:32:00Z"),
]

all_entries = [
    page0_entries, page1_entries, page2_entries,
    page3_entries, page4_entries, page5_entries,
]
initial_pages = [encode_page(e) for e in all_entries]

# --- Modified pages for WAL transactions -----------------------------

# Txn 1001 - committed: update config:version, add user:3
txn1001_p0 = encode_page([
    ("config:version",    "2.0.0"),
    ("config:name",       "testdb"),
    ("config:created_at", "2024-01-15T10:30:00Z"),
])
txn1001_p1 = encode_page([
    ("user:1:name",  "Alice"),
    ("user:1:email", "alice@example.com"),
    ("user:2:name",  "Bob"),
    ("user:2:email", "bob@example.com"),
    ("user:3:name",  "Charlie"),
    ("user:3:email", "charlie@example.com"),
])

# Txn 1002 - uncommitted: delete user:1, add user:4
txn1002_p1 = encode_page([
    ("user:2:name",  "Bob"),
    ("user:2:email", "bob@example.com"),
    ("user:4:name",  "Dave"),
    ("user:4:email", "dave@example.com"),
])

# Txn 1003 - committed: counter update (same page, two writes)
txn1003_p2_v1 = encode_page([
    ("counter:visits",  "100"),
    ("counter:errors",  "7"),
    ("counter:signups", "15"),
])
txn1003_p2_v2 = encode_page([
    ("counter:visits",  "108"),
    ("counter:errors",  "7"),
    ("counter:signups", "15"),
])

# Txn 1004 - aborted: rename user:2 to Robert
txn1004_p1 = encode_page([
    ("user:1:name",  "Alice"),
    ("user:1:email", "alice@example.com"),
    ("user:2:name",  "Robert"),
    ("user:2:email", "bob@example.com"),
    ("user:3:name",  "Charlie"),
    ("user:3:email", "charlie@example.com"),
])

# Txn 1005 - corrupted BEGIN: add session:ghi789, modify permissions
txn1005_p3 = encode_page([
    ("session:abc123", "user:1"),
    ("session:def456", "user:2"),
    ("session:ghi789", "user:3"),
])
txn1005_p4 = encode_page([
    ("perm:admin:read",  "true"),
    ("perm:admin:write", "true"),
    ("perm:guest:read",  "true"),
    ("perm:user:read",   "true"),
    ("perm:user:write",  "true"),
])

# Txn 1006 - committed: rename user:2 to Bobby, add session:jkl012
txn1006_p1 = encode_page([
    ("user:1:name",  "Alice"),
    ("user:1:email", "alice@example.com"),
    ("user:2:name",  "Bobby"),
    ("user:2:email", "bob@example.com"),
    ("user:3:name",  "Charlie"),
    ("user:3:email", "charlie@example.com"),
])
txn1006_p3 = encode_page([
    ("session:abc123", "user:1"),
    ("session:def456", "user:2"),
    ("session:jkl012", "user:3"),
])

# Txn 1007 - truncated (crash mid-write)
txn1007_p2 = encode_page([
    ("counter:visits",  "999"),
    ("counter:errors",  "0"),
    ("counter:signups", "100"),
])

# --- WAL frames -------------------------------------------------------

frames = [
    make_frame(BEGIN, 1001),
    make_frame(PAGE_WRITE, 1001, 0, txn1001_p0),
    make_frame(BEGIN, 1002),
    make_frame(PAGE_WRITE, 1002, 1, txn1002_p1),
    make_frame(PAGE_WRITE, 1001, 1, txn1001_p1),
    make_frame(COMMIT, 1001),
    make_frame(BEGIN, 1003),
    make_frame(PAGE_WRITE, 1003, 2, txn1003_p2_v1),
    make_frame(PAGE_WRITE, 1003, 2, txn1003_p2_v2),
    make_frame(BEGIN, 1004),
    make_frame(COMMIT, 1003),
    make_frame(PAGE_WRITE, 1004, 1, txn1004_p1),
    make_frame(ABORT, 1004),
    make_frame(COMMIT, 9999),                          # phantom -- no BEGIN
    make_frame(BEGIN, 1005, corrupt_crc=True),          # corrupted CRC
    make_frame(PAGE_WRITE, 1005, 3, txn1005_p3),
    make_frame(PAGE_WRITE, 1005, 4, txn1005_p4),       # writes to page 4
    make_frame(COMMIT, 1005),
    make_frame(BEGIN, 1006),
    make_frame(PAGE_WRITE, 1006, 1, txn1006_p1),
    make_frame(PAGE_WRITE, 1006, 3, txn1006_p3),
    make_frame(COMMIT, 1006),
    make_frame(BEGIN, 1007),
    make_frame(PAGE_WRITE, 1007, 2, txn1007_p2),       # will be truncated
]

# --- Write files -------------------------------------------------------

os.makedirs('/app', exist_ok=True)

# 1. Write clean database, then corrupt it
write_db('/app/data.db', initial_pages)
db_checksum = pages_checksum(initial_pages)

# Corrupt data.db -- scramble bytes in every page so CRC fails
# and individual pages cannot be trusted
with open('/app/data.db', 'r+b') as f:
    for page_idx in range(len(initial_pages)):
        offset = HEADER_SIZE + page_idx * PAGE_SIZE + 10
        f.seek(offset)
        f.write(b'\xDE\xAD\xBE\xEF' * 4)

# 2. WAL (last frame truncated to simulate crash)
write_wal('/app/wal.log', db_checksum, frames, truncate_last=True)

# 3. SQLite backup of pre-WAL state
create_sqlite_backup('/app/backup.sqlite', all_entries, initial_pages)

print("Setup complete:")
print(f"  /app/data.db        (corrupted -- CRC will fail)")
print(f"  /app/wal.log        ({len(frames)} frames, last truncated)")
print(f"  /app/backup.sqlite  (pre-WAL snapshot, {len(all_entries)} pages)")
