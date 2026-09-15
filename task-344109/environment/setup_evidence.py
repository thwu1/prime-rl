#!/usr/bin/env python3
"""Generate forensic evidence container with embedded ZIP archives and case database."""

import struct
import zlib
import os
import hashlib
import sqlite3
import random

EVIDENCE_PATH = "/app/evidence.bin"
DB_PATH = "/app/casedb.sqlite"


def dos_time_val(hour, minute, second):
    return (hour << 11) | (minute << 5) | (second // 2)


def dos_date_val(year, month, day):
    return ((year - 1980) << 9) | (month << 5) | day


def build_local_header(fname_bytes, data, flags, comp, dtime, ddate):
    crc = zlib.crc32(data) & 0xFFFFFFFF
    hdr = struct.pack(
        '<4sHHHHHIIIHH',
        b'PK\x03\x04', 20, flags, comp, dtime, ddate,
        crc, len(data), len(data), len(fname_bytes), 0,
    )
    return hdr + fname_bytes + data


def build_cd_entry(fname_bytes, data_len, crc, local_offset, flags, comp, dtime, ddate):
    entry = struct.pack(
        '<4sHHHHHHIIIHHHHHII',
        b'PK\x01\x02', 20, 20, flags, comp, dtime, ddate,
        crc, data_len, data_len, len(fname_bytes),
        0, 0, 0, 0, 0, local_offset,
    )
    return entry + fname_bytes


def build_eocd(num_entries, cd_size, cd_offset, comment=b""):
    return struct.pack(
        '<4sHHHHIIH',
        b'PK\x05\x06', 0, 0,
        num_entries, num_entries,
        cd_size, cd_offset, len(comment),
    ) + comment


def make_simple_zip(entries_spec, prepend=b""):
    file_data = b""
    cd_data = b""
    for fname_bytes, data, flags, comp, dt, dd in entries_spec:
        crc = zlib.crc32(data) & 0xFFFFFFFF
        local_offset = len(file_data)
        local_hdr = build_local_header(fname_bytes, data, flags, comp, dt, dd)
        file_data += local_hdr
        cd_entry = build_cd_entry(
            fname_bytes, len(data), crc, local_offset, flags, comp, dt, dd
        )
        cd_data += cd_entry
    cd_offset = len(file_data)
    eocd = build_eocd(len(entries_spec), len(cd_data), cd_offset)
    return prepend + file_data + cd_data + eocd


def generate_stored_zip():
    dt = dos_time_val(14, 30, 0)
    dd = dos_date_val(2024, 12, 25)
    return make_simple_zip([(b"hello.txt", b"Hello, World!", 0, 0, dt, dd)])


def generate_sjis_zip():
    fname_sjis = b"\x83\x65\x83\x58\x83\x67\x2e\x74\x78\x74"
    dt = dos_time_val(10, 15, 0)
    dd = dos_date_val(2023, 6, 15)
    return make_simple_zip([(fname_sjis, b"sjis content", 0, 0, dt, dd)])


def generate_fake_eocd_zip():
    fname = b"readme.txt"
    data = b"This is a test file with nothing special about its data."
    dt = dos_time_val(9, 0, 0)
    dd = dos_date_val(2025, 1, 10)
    crc = zlib.crc32(data) & 0xFFFFFFFF

    local_hdr = build_local_header(fname, data, 0, 0, dt, dd)
    cd_entry = build_cd_entry(fname, len(data), crc, 0, 0, 0, dt, dd)
    cd_offset = len(local_hdr)

    comment = b"TRAP:" + b"\x50\x4b\x05\x06" + b"\x00" * 18 + b":END"
    eocd = build_eocd(1, len(cd_entry), cd_offset, comment)
    return local_hdr + cd_entry + eocd


def generate_prepended_zip():
    prepend_data = b"\x7fELF" + b"\x00" * 4092
    dt = dos_time_val(16, 45, 30)
    dd = dos_date_val(2024, 7, 4)
    return make_simple_zip(
        [(b"payload.txt", b"Extracted!", 0, 0, dt, dd)],
        prepend=prepend_data,
    )


def generate_zip64_zip():
    fname = b"data.txt"
    data = b"zip64 content here"
    dt = dos_time_val(12, 0, 0)
    dd = dos_date_val(2025, 3, 20)
    crc = zlib.crc32(data) & 0xFFFFFFFF

    local_hdr = struct.pack(
        '<4sHHHHHIIIHH',
        b'PK\x03\x04', 45, 0, 0, dt, dd,
        crc, len(data), len(data), len(fname), 0,
    ) + fname + data

    cd_offset5 = len(local_hdr)
    cd_entry = struct.pack(
        '<4sHHHHHHIIIHHHHHII',
        b'PK\x01\x02', 45, 45, 0, 0, dt, dd,
        crc, len(data), len(data), len(fname),
        0, 0, 0, 0, 0, 0,
    ) + fname
    cd_size = len(cd_entry)

    zip64_eocd_offset = cd_offset5 + cd_size
    zip64_eocd = struct.pack(
        '<4sQHHIIQQQQ',
        b'PK\x06\x06', 44, 45, 45, 0, 0, 1, 1, cd_size, cd_offset5,
    )
    zip64_locator = struct.pack(
        '<4sIQI', b'PK\x06\x07', 0, zip64_eocd_offset, 1,
    )
    eocd = struct.pack(
        '<4sHHHHIIH',
        b'PK\x05\x06', 0, 0,
        0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0,
    )
    return local_hdr + cd_entry + zip64_eocd + zip64_locator + eocd


def random_padding(rng, min_len=200, max_len=600):
    """Generate deterministic random padding free of PK signatures."""
    length = rng.randint(min_len, max_len)
    while True:
        data = bytes(rng.getrandbits(8) for _ in range(length))
        if b'PK' not in data:
            return data


def main():
    os.makedirs("/app", exist_ok=True)
    rng = random.Random(42)

    archives = [
        ("stored", generate_stored_zip()),
        ("sjis", generate_sjis_zip()),
        ("fake_eocd", generate_fake_eocd_zip()),
        ("prepended", generate_prepended_zip()),
        ("zip64", generate_zip64_zip()),
    ]

    # Build evidence container
    header = b"EVDNC_CONTAINER_V1\x00" + b"\x00" * 13  # 32 bytes total
    evidence = bytearray(header)

    specimen_info = []
    for i, (name, zip_data) in enumerate(archives, 1):
        padding = random_padding(rng, 200, 600)
        offset = len(evidence) + len(padding)
        evidence.extend(padding)
        evidence.extend(zip_data)
        sha = hashlib.sha256(zip_data).hexdigest()
        specimen_info.append((i, name, offset, len(zip_data), sha))

    # Trailing padding
    evidence.extend(random_padding(rng, 64, 256))

    with open(EVIDENCE_PATH, "wb") as f:
        f.write(evidence)

    # Create SQLite case database
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "CREATE TABLE case_info ("
        "case_id TEXT PRIMARY KEY, "
        "analyst TEXT, "
        "date TEXT, "
        "description TEXT)"
    )
    c.execute(
        "INSERT INTO case_info VALUES (?, ?, ?, ?)",
        (
            "CASE-2024-0847",
            "J. Chen",
            "2024-12-28",
            "Recovered ZIP archives from carved storage media",
        ),
    )

    c.execute(
        "CREATE TABLE specimens ("
        "specimen_id INTEGER PRIMARY KEY, "
        "sha256 TEXT UNIQUE, "
        "case_ref TEXT, "
        "notes TEXT)"
    )

    for sid, name, offset, size, sha in specimen_info:
        c.execute(
            "INSERT INTO specimens VALUES (?, ?, ?, ?)",
            (sid, sha, f"CASE-2024-0847-SP{sid:03d}", f"Carved specimen #{sid}"),
        )

    conn.commit()
    conn.close()

    print(f"Evidence container: {len(evidence)} bytes at {EVIDENCE_PATH}")
    print(f"Database: {DB_PATH}")
    print(f"Specimens embedded: {len(specimen_info)}")
    for sid, name, offset, size, sha in specimen_info:
        print(f"  #{sid} ({name}): offset={offset}, size={size}, sha256={sha[:16]}...")


if __name__ == "__main__":
    main()
