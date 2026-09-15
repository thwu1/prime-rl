#!/usr/bin/env python3
"""
ZIP Forensic Analyzer — raw binary parser.
Handles structural variations including extended format records, non-ASCII
filename encodings, ambiguous end-of-archive markers, and offset-shifted archives.
No zipfile module or third-party ZIP libraries used.
"""

import struct
import sys
import json
import zlib


def find_eocd(data):
    """
    Locate the real End of Central Directory record by scanning backward
    and validating each candidate against structural consistency constraints.
    """
    file_size = len(data)
    min_offset = max(0, file_size - 22 - 65535)
    pos = file_size - 22
    while pos >= min_offset:
        if data[pos:pos + 4] == b'PK\x05\x06':
            comment_len = struct.unpack_from('<H', data, pos + 20)[0]
            if pos + 22 + comment_len == file_size:
                return pos
        pos -= 1
    raise ValueError("No valid EOCD record found")


def parse_eocd(data, offset):
    fields = struct.unpack_from('<4sHHHHIIH', data, offset)
    return {
        'entries_disk': fields[3],
        'entries_total': fields[4],
        'cd_size': fields[5],
        'cd_offset': fields[6],
        'comment_len': fields[7],
    }


def check_zip64(data, eocd_offset):
    """Check for Zip64 EOCD structures preceding the standard EOCD."""
    loc_off = eocd_offset - 20
    if loc_off < 0 or data[loc_off:loc_off + 4] != b'PK\x06\x07':
        return None
    _, disk_z64, z64_eocd_off, total_disks = struct.unpack_from(
        '<4sIQI', data, loc_off
    )
    z64_eocd_off = int(z64_eocd_off)
    if z64_eocd_off + 56 > len(data):
        return None
    if data[z64_eocd_off:z64_eocd_off + 4] != b'PK\x06\x06':
        return None
    z = struct.unpack_from('<4sQHHIIQQQQ', data, z64_eocd_off)
    return {
        'zip64_eocd_offset': z64_eocd_off,
        'entries_total': int(z[6]),
        'cd_size': int(z[8]),
        'cd_offset': int(z[9]),
    }


def detect_encoding(raw_bytes, flags):
    """Detect filename encoding from byte patterns and flags."""
    if flags & (1 << 11):
        return 'utf-8'
    if all(b < 0x80 for b in raw_bytes):
        return 'utf-8'
    # Check for valid double-byte encoding sequences
    i = 0
    db_pairs = 0
    while i < len(raw_bytes):
        b = raw_bytes[i]
        if (0x81 <= b <= 0x9F) or (0xE0 <= b <= 0xEF):
            if i + 1 < len(raw_bytes):
                trail = raw_bytes[i + 1]
                if (0x40 <= trail <= 0x7E) or (0x80 <= trail <= 0xFC):
                    db_pairs += 1
                    i += 2
                    continue
        i += 1
    if db_pairs > 0:
        try:
            raw_bytes.decode('shift_jis')
            return 'shift_jis'
        except Exception:
            pass
    return 'cp437'


def dos_to_iso(dos_time, dos_date):
    """Convert DOS packed time/date to ISO 8601."""
    sec = (dos_time & 0x1F) * 2
    minute = (dos_time >> 5) & 0x3F
    hour = (dos_time >> 11) & 0x1F
    day = dos_date & 0x1F
    month = (dos_date >> 5) & 0x0F
    year = ((dos_date >> 9) & 0x7F) + 1980
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{sec:02d}"


def parse_central_directory(data, cd_start, count, prepend_adjust):
    entries = []
    pos = cd_start
    for _ in range(count):
        sig = data[pos:pos + 4]
        if sig != b'PK\x01\x02':
            raise ValueError(f"Invalid CD entry signature at offset {pos}")
        f = struct.unpack_from('<4sHHHHHHIIIHHHHHII', data, pos)
        flags = f[3]
        comp = f[4]
        dtime = f[5]
        ddate = f[6]
        crc = f[7]
        csz = f[8]
        usz = f[9]
        fn_len = f[10]
        ex_len = f[11]
        cm_len = f[12]
        loc_off = f[16]

        raw_name = data[pos + 46:pos + 46 + fn_len]
        enc = detect_encoding(raw_name, flags)
        filename = raw_name.decode(enc)

        entries.append({
            'filename': filename,
            'filename_encoding': enc,
            'compressed_size': csz,
            'uncompressed_size': usz,
            'compression_method': comp,
            'mod_datetime': dos_to_iso(dtime, ddate),
            'crc32': f"{crc:08x}",
            'local_header_offset': loc_off + prepend_adjust,
        })
        pos += 46 + fn_len + ex_len + cm_len
    return entries


def analyze(filepath):
    with open(filepath, 'rb') as fh:
        data = fh.read()

    eocd_off = find_eocd(data)
    eocd = parse_eocd(data, eocd_off)

    z64 = check_zip64(data, eocd_off)
    is_zip64 = z64 is not None

    if is_zip64:
        n_entries = z64['entries_total']
        cd_size = z64['cd_size']
        stored_cd_offset = z64['cd_offset']
        cd_end_marker = z64['zip64_eocd_offset']
    else:
        n_entries = eocd['entries_total']
        cd_size = eocd['cd_size']
        stored_cd_offset = eocd['cd_offset']
        cd_end_marker = eocd_off

    actual_cd_start = cd_end_marker - cd_size
    prepend_size = actual_cd_start - stored_cd_offset

    entries = parse_central_directory(data, actual_cd_start, n_entries, prepend_size)

    return {
        'eocd_offset': eocd_off,
        'total_entries': n_entries,
        'central_directory_offset': actual_cd_start,
        'is_zip64': is_zip64,
        'prepended_data_size': prepend_size,
        'entries': entries,
    }


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: zipforensics.py <file>", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(analyze(sys.argv[1]), indent=2, ensure_ascii=False))
