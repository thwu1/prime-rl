#!/usr/bin/env python3
"""
ESP-IDF Partition Table Forensics Tool

Parses, diagnoses, and repairs corrupted ESP-IDF partition table binary files.

Usage:
    ptable_forensics.py parse <binary_file>
    ptable_forensics.py diagnose <binary_file>
    ptable_forensics.py repair <binary_file> <output_file>
"""

import sys
import json
import struct
import hashlib
import os
import argparse

# ESP-IDF partition table constants
MAGIC = b'\xaa\x50'
STRUCT_FMT = '<2sBBLL16sL'
MD5_MARKER_PREFIX = b'\xeb\xeb' + b'\xff' * 14
MAX_PART_LEN = 0xC00
PARTITION_TABLE_SIZE = 0x1000
DEFAULT_PTABLE_OFFSET = 0x8000

APP_TYPE = 0x00
DATA_TYPE = 0x01

# Offset alignment requirements by partition type
ALIGNMENT_OFFSET = {
    APP_TYPE: 0x10000,   # 64 KB
    DATA_TYPE: 0x1000,   # 4 KB
}

# Data subtypes with specific size constraints
NVS_SUBTYPE = 0x02
OTA_DATA_SUBTYPE = 0x00
NVS_RW_MIN_SIZE = 0x3000
OTA_DATA_EXACT_SIZE = 0x2000

# Flag bit definitions: only bits 0 (encrypted) and 1 (readonly) are valid
KNOWN_FLAG_MASK = 0x00000003


def parse_binary(filepath):
    """Parse a partition table binary, handling corruptions gracefully.

    Returns (entries_list, md5_info_dict).
    """
    with open(filepath, 'rb') as f:
        data = f.read()

    entries = []
    md5_info = {'present': False, 'valid': None}
    raw_entry_data = b''

    for offset in range(0, min(len(data), MAX_PART_LEN), 32):
        chunk = data[offset:offset + 32]
        if len(chunk) != 32:
            break

        # End marker: 32 bytes of 0xFF
        if chunk == b'\xff' * 32:
            break

        # MD5 marker: starts with 0xEB 0xEB
        if chunk[:2] == b'\xeb\xeb':
            md5_info['present'] = True
            expected = hashlib.md5(raw_entry_data).digest()
            actual = chunk[16:]
            md5_info['valid'] = (expected == actual)
            md5_info['expected'] = expected.hex()
            md5_info['actual'] = actual.hex()
            continue

        # Parse as partition entry (tolerant of bad magic)
        magic, type_, subtype, part_offset, size, name_bytes, flags = \
            struct.unpack(STRUCT_FMT, chunk)

        # Decode name: null-terminated, ASCII
        if b'\x00' in name_bytes:
            name_bytes = name_bytes[:name_bytes.index(b'\x00')]
        name = name_bytes.decode('ascii', errors='replace')

        entries.append({
            'index': len(entries),
            'name': name,
            'type': type_,
            'subtype': subtype,
            'offset': part_offset,
            'size': size,
            'flags': flags,
            'valid_magic': (magic == MAGIC),
        })
        raw_entry_data += chunk

    return entries, md5_info


def diagnose_table(filepath):
    """Diagnose all issues in a partition table binary.

    Returns a list of issue dicts.
    """
    entries, md5_info = parse_binary(filepath)
    issues = []

    for entry in entries:
        idx = entry['index']
        ptype = entry['type']

        # Invalid magic bytes
        if not entry['valid_magic']:
            issues.append({
                'entry_index': idx,
                'issue_type': 'invalid_magic',
                'description': (
                    f"Entry '{entry['name']}' at index {idx} has invalid magic bytes"
                ),
            })

        # Offset alignment check
        align = ALIGNMENT_OFFSET.get(ptype, 0x1000)
        if entry['offset'] % align != 0:
            issues.append({
                'entry_index': idx,
                'issue_type': 'offset_not_aligned',
                'description': (
                    f"Entry '{entry['name']}' offset 0x{entry['offset']:x} "
                    f"is not aligned to 0x{align:x}"
                ),
            })

        # APP partition size must be 4KB-aligned
        if ptype == APP_TYPE and entry['size'] % 0x1000 != 0:
            issues.append({
                'entry_index': idx,
                'issue_type': 'app_size_not_aligned',
                'description': (
                    f"App partition '{entry['name']}' size 0x{entry['size']:x} "
                    f"is not aligned to 0x1000"
                ),
            })

        # NVS minimum size (read-write partitions only)
        if ptype == DATA_TYPE and entry['subtype'] == NVS_SUBTYPE:
            is_readonly = bool(entry['flags'] & 0x2)
            if not is_readonly and entry['size'] < NVS_RW_MIN_SIZE:
                issues.append({
                    'entry_index': idx,
                    'issue_type': 'nvs_too_small',
                    'description': (
                        f"NVS partition '{entry['name']}' size 0x{entry['size']:x} "
                        f"is below minimum 0x{NVS_RW_MIN_SIZE:x} for read-write NVS"
                    ),
                })

        # OTA data partition must be exactly 0x2000
        if ptype == DATA_TYPE and entry['subtype'] == OTA_DATA_SUBTYPE:
            if entry['size'] != OTA_DATA_EXACT_SIZE:
                issues.append({
                    'entry_index': idx,
                    'issue_type': 'otadata_wrong_size',
                    'description': (
                        f"OTA data partition '{entry['name']}' size 0x{entry['size']:x} "
                        f"must be exactly 0x{OTA_DATA_EXACT_SIZE:x}"
                    ),
                })

        # Unknown flag bits
        if entry['flags'] & ~KNOWN_FLAG_MASK:
            unknown_bits = entry['flags'] & ~KNOWN_FLAG_MASK
            issues.append({
                'entry_index': idx,
                'issue_type': 'unknown_flags',
                'description': (
                    f"Entry '{entry['name']}' has unknown flag bits set: "
                    f"0x{unknown_bits:08x}"
                ),
            })

    # Duplicate partition names
    seen_names = {}
    for entry in entries:
        name = entry['name']
        if name in seen_names:
            issues.append({
                'entry_index': entry['index'],
                'issue_type': 'duplicate_name',
                'description': (
                    f"Duplicate partition name '{name}' "
                    f"(first seen at index {seen_names[name]})"
                ),
            })
        else:
            seen_names[name] = entry['index']

    # Overlapping partitions (check in offset order)
    sorted_entries = sorted(entries, key=lambda e: e['offset'])
    for i in range(len(sorted_entries) - 1):
        curr = sorted_entries[i]
        nxt = sorted_entries[i + 1]
        curr_end = curr['offset'] + curr['size']
        if curr_end > nxt['offset']:
            issues.append({
                'entry_index': nxt['index'],
                'issue_type': 'overlap',
                'description': (
                    f"Partition '{nxt['name']}' at 0x{nxt['offset']:x} overlaps with "
                    f"'{curr['name']}' (0x{curr['offset']:x}-0x{curr_end:x})"
                ),
            })

    # MD5 checksum validity
    if md5_info['present'] and not md5_info['valid']:
        issues.append({
            'issue_type': 'invalid_md5',
            'description': (
                f"MD5 checksum mismatch: computed {md5_info.get('expected', '?')}, "
                f"stored {md5_info.get('actual', '?')}"
            ),
        })

    return issues


def repair_table(filepath, output_path):
    """Repair all issues in a corrupted partition table binary.

    Applies fixes in dependency order:
    1. Fix sizes (NVS minimum, otadata exact, APP alignment)
    2. Deduplicate names
    3. Clear unknown flag bits
    4. Fix offset alignment
    5. Resolve overlaps
    6. Reconstruct binary with valid magic and recomputed MD5
    """
    entries, _ = parse_binary(filepath)

    # Step 1: Fix size constraints
    for entry in entries:
        ptype = entry['type']

        # NVS read-write minimum
        if ptype == DATA_TYPE and entry['subtype'] == NVS_SUBTYPE:
            is_readonly = bool(entry['flags'] & 0x2)
            if not is_readonly and entry['size'] < NVS_RW_MIN_SIZE:
                entry['size'] = NVS_RW_MIN_SIZE

        # OTA data exact size
        if ptype == DATA_TYPE and entry['subtype'] == OTA_DATA_SUBTYPE:
            if entry['size'] != OTA_DATA_EXACT_SIZE:
                entry['size'] = OTA_DATA_EXACT_SIZE

        # APP size 4KB alignment
        if ptype == APP_TYPE:
            if entry['size'] % 0x1000 != 0:
                entry['size'] = ((entry['size'] + 0xFFF) // 0x1000) * 0x1000

    # Step 2: Deduplicate names
    name_count = {}
    for entry in entries:
        name = entry['name']
        if name in name_count:
            name_count[name] += 1
            new_name = f"{name}_{name_count[name]}"
            # Truncate to 15 chars (16 bytes including null terminator)
            if len(new_name) > 15:
                new_name = new_name[:15]
            entry['name'] = new_name
        else:
            name_count[name] = 0

    # Step 3: Clear unknown flag bits
    for entry in entries:
        entry['flags'] = entry['flags'] & KNOWN_FLAG_MASK

    # Step 4: Fix offset alignment
    for entry in entries:
        ptype = entry['type']
        align = ALIGNMENT_OFFSET.get(ptype, 0x1000)
        if entry['offset'] % align != 0:
            entry['offset'] = ((entry['offset'] + align - 1) // align) * align

    # Step 5: Resolve overlaps (process in offset order, shift later partitions)
    by_offset = sorted(entries, key=lambda e: e['offset'])
    for i in range(1, len(by_offset)):
        prev = by_offset[i - 1]
        curr = by_offset[i]
        prev_end = prev['offset'] + prev['size']
        if curr['offset'] < prev_end:
            align = ALIGNMENT_OFFSET.get(curr['type'], 0x1000)
            curr['offset'] = ((prev_end + align - 1) // align) * align

    # Step 6: Reconstruct binary with valid magic and correct MD5
    result = b''
    for entry in entries:
        name_bytes = entry['name'].encode('ascii')[:16].ljust(16, b'\x00')
        result += struct.pack(
            STRUCT_FMT,
            MAGIC,
            entry['type'],
            entry['subtype'],
            entry['offset'],
            entry['size'],
            name_bytes,
            entry['flags'],
        )

    # Append MD5 marker + digest
    md5_digest = hashlib.md5(result).digest()
    result += MD5_MARKER_PREFIX + md5_digest

    # Pad to 0xC00 with 0xFF
    result += b'\xff' * (MAX_PART_LEN - len(result))

    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(result)


def main():
    parser = argparse.ArgumentParser(
        description='ESP-IDF Partition Table Forensics Tool'
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    # parse subcommand
    p_parse = subparsers.add_parser('parse',
                                     help='Parse a partition table binary')
    p_parse.add_argument('binary_file', help='Path to binary file')

    # diagnose subcommand
    p_diag = subparsers.add_parser('diagnose',
                                    help='Diagnose issues in a partition table')
    p_diag.add_argument('binary_file', help='Path to binary file')

    # repair subcommand
    p_repair = subparsers.add_parser('repair',
                                      help='Repair a corrupted partition table')
    p_repair.add_argument('binary_file', help='Path to input binary file')
    p_repair.add_argument('output_file', help='Path to output repaired binary')

    args = parser.parse_args()

    if args.command == 'parse':
        entries, md5_info = parse_binary(args.binary_file)
        output = {'entries': entries, 'md5': md5_info}
        print(json.dumps(output, indent=2))

    elif args.command == 'diagnose':
        issues = diagnose_table(args.binary_file)
        print(json.dumps(issues, indent=2))

    elif args.command == 'repair':
        repair_table(args.binary_file, args.output_file)
        print(json.dumps({'status': 'success', 'output': args.output_file}))


if __name__ == '__main__':
    main()
