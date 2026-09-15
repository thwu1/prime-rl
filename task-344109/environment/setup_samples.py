#!/usr/bin/env python3
"""Generate edge-case ZIP archive samples for forensic analysis."""

import struct
import zlib
import os

SAMPLES_DIR = "/app/samples"


def dos_time_val(hour, minute, second):
    return (hour << 11) | (minute << 5) | (second // 2)


def dos_date_val(year, month, day):
    return ((year - 1980) << 9) | (month << 5) | day


def build_local_header(fname_bytes, data, flags, comp, dtime, ddate):
    crc = zlib.crc32(data) & 0xFFFFFFFF
    hdr = struct.pack(
        '<4sHHHHHIIIHH',
        b'PK\x03\x04',
        20,
        flags,
        comp,
        dtime,
        ddate,
        crc,
        len(data),
        len(data),
        len(fname_bytes),
        0,
    )
    return hdr + fname_bytes + data


def build_cd_entry(fname_bytes, data_len, crc, local_offset, flags, comp, dtime, ddate):
    entry = struct.pack(
        '<4sHHHHHHIIIHHHHHII',
        b'PK\x01\x02',
        20,
        20,
        flags,
        comp,
        dtime,
        ddate,
        crc,
        data_len,
        data_len,
        len(fname_bytes),
        0,
        0,
        0,
        0,
        0,
        local_offset,
    )
    return entry + fname_bytes


def build_eocd(num_entries, cd_size, cd_offset, comment=b""):
    return struct.pack(
        '<4sHHHHIIH',
        b'PK\x05\x06',
        0, 0,
        num_entries, num_entries,
        cd_size,
        cd_offset,
        len(comment),
    ) + comment


def make_simple_zip(entries_spec, prepend=b""):
    """
    entries_spec: list of (fname_bytes, data, flags, comp, dtime, ddate)
    Offsets in the CD are relative to start of ZIP data (after prepend).
    """
    file_data = b""
    cd_data = b""

    for fname_bytes, data, flags, comp, dt, dd in entries_spec:
        crc = zlib.crc32(data) & 0xFFFFFFFF
        local_offset = len(file_data)
        local_hdr = build_local_header(fname_bytes, data, flags, comp, dt, dd)
        file_data += local_hdr
        cd_entry = build_cd_entry(fname_bytes, len(data), crc, local_offset, flags, comp, dt, dd)
        cd_data += cd_entry

    cd_offset = len(file_data)
    eocd = build_eocd(len(entries_spec), len(cd_data), cd_offset)
    return prepend + file_data + cd_data + eocd


def main():
    os.makedirs(SAMPLES_DIR, exist_ok=True)

    # ---- Sample 1: sample_stored.zip ----
    # Basic stored ZIP with known DOS timestamp: 2024-12-25 14:30:00
    dt1 = dos_time_val(14, 30, 0)
    dd1 = dos_date_val(2024, 12, 25)
    zip1 = make_simple_zip([(b"hello.txt", b"Hello, World!", 0, 0, dt1, dd1)])
    with open(os.path.join(SAMPLES_DIR, "sample_stored.zip"), "wb") as f:
        f.write(zip1)

    # ---- Sample 2: sample_sjis.zip ----
    # Shift-JIS encoded filename, UTF-8 flag NOT set
    # テスト.txt in Shift-JIS: \x83\x65\x83\x58\x83\x67 + .txt
    fname_sjis = b"\x83\x65\x83\x58\x83\x67\x2e\x74\x78\x74"
    dt2 = dos_time_val(10, 15, 0)
    dd2 = dos_date_val(2023, 6, 15)
    zip2 = make_simple_zip([(fname_sjis, b"sjis content", 0, 0, dt2, dd2)])
    with open(os.path.join(SAMPLES_DIR, "sample_sjis.zip"), "wb") as f:
        f.write(zip2)

    # ---- Sample 3: sample_fake_eocd.zip ----
    # EOCD comment contains a fake PK\x05\x06 signature
    fname3 = b"readme.txt"
    data3 = b"This is a test file with nothing special about its data."
    dt3 = dos_time_val(9, 0, 0)
    dd3 = dos_date_val(2025, 1, 10)
    crc3 = zlib.crc32(data3) & 0xFFFFFFFF

    local_hdr3 = build_local_header(fname3, data3, 0, 0, dt3, dd3)
    cd_entry3 = build_cd_entry(fname3, len(data3), crc3, 0, 0, 0, dt3, dd3)
    cd_offset3 = len(local_hdr3)

    # Comment with embedded fake EOCD signature
    comment3 = b"TRAP:" + b"\x50\x4b\x05\x06" + b"\x00" * 18 + b":END"
    eocd3 = build_eocd(1, len(cd_entry3), cd_offset3, comment3)
    zip3 = local_hdr3 + cd_entry3 + eocd3
    with open(os.path.join(SAMPLES_DIR, "sample_fake_eocd.zip"), "wb") as f:
        f.write(zip3)

    # ---- Sample 4: sample_prepended.zip ----
    # 4096 bytes of fake ELF header prepended to a valid ZIP
    prepend_data = b"\x7fELF" + b"\x00" * 4092  # 4096 bytes
    dt4 = dos_time_val(16, 45, 30)
    dd4 = dos_date_val(2024, 7, 4)
    zip4 = make_simple_zip(
        [(b"payload.txt", b"Extracted!", 0, 0, dt4, dd4)],
        prepend=prepend_data,
    )
    with open(os.path.join(SAMPLES_DIR, "sample_prepended.zip"), "wb") as f:
        f.write(zip4)

    # ---- Sample 5: sample_zip64.zip ----
    # Zip64 EOCD Record + Locator with sentinel values in standard EOCD
    fname5 = b"data.txt"
    data5 = b"zip64 content here"
    dt5 = dos_time_val(12, 0, 0)
    dd5 = dos_date_val(2025, 3, 20)
    crc5 = zlib.crc32(data5) & 0xFFFFFFFF

    local_hdr5 = struct.pack(
        '<4sHHHHHIIIHH',
        b'PK\x03\x04', 45, 0, 0, dt5, dd5,
        crc5, len(data5), len(data5), len(fname5), 0,
    ) + fname5 + data5

    cd_offset5 = len(local_hdr5)
    cd_entry5 = struct.pack(
        '<4sHHHHHHIIIHHHHHII',
        b'PK\x01\x02', 45, 45, 0, 0, dt5, dd5,
        crc5, len(data5), len(data5), len(fname5),
        0, 0, 0, 0, 0, 0,
    ) + fname5
    cd_size5 = len(cd_entry5)

    # Zip64 EOCD record (56 bytes)
    zip64_eocd_offset = cd_offset5 + cd_size5
    zip64_eocd = struct.pack(
        '<4sQHHIIQQQQ',
        b'PK\x06\x06',
        44,     # size of remaining record
        45, 45, # version made / needed
        0, 0,   # disk / disk with CD
        1, 1,   # entries on disk / total entries
        cd_size5,
        cd_offset5,
    )

    # Zip64 EOCD locator (20 bytes)
    zip64_locator = struct.pack(
        '<4sIQI',
        b'PK\x06\x07',
        0,
        zip64_eocd_offset,
        1,
    )

    # Standard EOCD with sentinel values
    eocd5 = struct.pack(
        '<4sHHHHIIH',
        b'PK\x05\x06',
        0, 0,
        0xFFFF, 0xFFFF,
        0xFFFFFFFF,
        0xFFFFFFFF,
        0,
    )

    zip5 = local_hdr5 + cd_entry5 + zip64_eocd + zip64_locator + eocd5
    with open(os.path.join(SAMPLES_DIR, "sample_zip64.zip"), "wb") as f:
        f.write(zip5)

    print(f"Generated {len(os.listdir(SAMPLES_DIR))} samples in {SAMPLES_DIR}")


if __name__ == "__main__":
    main()
