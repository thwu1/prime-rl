#!/usr/bin/env python3
"""
ESP-IDF Flash Forensics Tool

Analyzes raw ESP32 flash memory dumps to identify content regions,
reconstruct corrupted partition tables, and validate partition table binaries.

Usage:
    flash_forensics.py scan <flash_dump>
    flash_forensics.py reconstruct <flash_dump> <output_file>
    flash_forensics.py check <partition_table_binary>
"""

import sys
import json
import struct
import hashlib
import zlib
import os
import argparse

# --- Flash constants ---
SECTOR = 0x1000  # 4KB sector size
PT_OFFSET = 0x8000  # Default partition table offset
PT_SIZE = 0x1000  # Partition table sector size
MAX_PT_DATA = 0xC00  # Max partition table data

# --- Partition table constants ---
PT_MAGIC = b'\xaa\x50'
PT_STRUCT = '<2sBBLL16sL'
PT_ENTRY_SIZE = 32
MD5_MARKER = b'\xeb\xeb' + b'\xff' * 14

APP_TYPE = 0x00
DATA_TYPE = 0x01

# --- Content signature constants ---
APP_IMAGE_MAGIC = 0xE9
NVS_VERSION = 0xFE
NVS_PAGE_ACTIVE = 0xFFFFFFFE
NVS_PAGE_FULL = 0xFFFFFFFC
PHY_MAGIC = bytes([0x04, 0x02, 0x00, 0x00])

# --- Alignment constraints ---
APP_OFFSET_ALIGN = 0x10000  # 64KB
DATA_OFFSET_ALIGN = 0x1000  # 4KB
APP_SIZE_ALIGN = 0x1000     # 4KB

# --- Size constraints ---
NVS_MIN_SIZE = 0x3000
OTA_DATA_SIZE = 0x2000

# --- Valid flag bits ---
KNOWN_FLAG_MASK = 0x00000003


def classify_sector(data):
    """Classify a 4KB sector by its binary content signature.

    Returns (content_type, details) where content_type is one of:
    'app', 'nvs', 'ota_data', 'phy', 'partition_table', 'erased', 'zeroed', 'data'
    """
    if len(data) < SECTOR:
        return ('short', {})

    if data == b'\xFF' * SECTOR:
        return ('erased', {})

    if data == b'\x00' * SECTOR:
        return ('zeroed', {})

    # --- APP image header (esp_image_header_t, 24 bytes) ---
    if data[0] == APP_IMAGE_MAGIC and len(data) >= 24:
        segment_count = data[1]
        entry_addr = struct.unpack('<I', data[4:8])[0]
        chip_id = struct.unpack('<H', data[12:14])[0]
        # Validate header fields
        if (1 <= segment_count <= 16
                and chip_id <= 0x0014
                and (entry_addr & 0xFF000000) in (0x40000000, 0x42000000, 0x3F000000)):
            return ('app', {
                'entry_addr': entry_addr,
                'segment_count': segment_count,
                'chip_id': chip_id,
            })

    # --- NVS page header (16 bytes) ---
    if len(data) >= 16:
        state = struct.unpack('<I', data[0:4])[0]
        if state in (NVS_PAGE_ACTIVE, NVS_PAGE_FULL):
            version = data[8]
            if version == NVS_VERSION:
                crc_data = data[4:12]  # seq_number + version + unused
                stored_crc = struct.unpack('<I', data[12:16])[0]
                computed_crc = zlib.crc32(crc_data) & 0xFFFFFFFF
                if stored_crc == computed_crc:
                    seq_no = struct.unpack('<I', data[4:8])[0]
                    return ('nvs', {'seq_no': seq_no, 'state': state})

    # --- OTA selection entry (32 bytes) ---
    if len(data) >= 32:
        ota_payload = data[0:28]
        stored_crc = struct.unpack('<I', data[28:32])[0]
        computed_crc = zlib.crc32(ota_payload) & 0xFFFFFFFF
        if stored_crc == computed_crc and data[4:24] == b'\xFF' * 20:
            ota_seq = struct.unpack('<I', data[0:4])[0]
            ota_state = struct.unpack('<I', data[24:28])[0]
            return ('ota_data', {'ota_seq': ota_seq, 'ota_state': ota_state})

    # --- PHY calibration data ---
    if data[0:4] == PHY_MAGIC:
        return ('phy', {})

    # --- Partition table entry ---
    if data[0:2] == PT_MAGIC:
        return ('partition_table', {})

    # --- Non-empty data (firmware content, etc.) ---
    return ('data', {})


def scan_flash(filepath):
    """Scan a flash dump sector-by-sector and identify all content regions.

    Returns a dict with 'flash_size' and 'regions' (list of region dicts).
    """
    with open(filepath, 'rb') as f:
        flash = f.read()

    flash_size = len(flash)
    num_sectors = flash_size // SECTOR

    # Phase 1: Classify every sector
    sector_info = []
    for i in range(num_sectors):
        offset = i * SECTOR
        sector_data = flash[offset:offset + SECTOR]
        ctype, details = classify_sector(sector_data)
        sector_info.append({
            'index': i,
            'offset': offset,
            'type': ctype,
            'details': details,
        })

    # Phase 2: Build regions by merging consecutive same-type sectors
    regions = []
    i = 0
    while i < len(sector_info):
        s = sector_info[i]
        stype = s['type']

        # Skip non-content sectors
        if stype in ('erased', 'zeroed', 'partition_table', 'short'):
            i += 1
            continue

        # APP: header sector + all following 'data' sectors
        if stype == 'app':
            start = s['offset']
            end_i = i + 1
            while end_i < len(sector_info):
                ntype = sector_info[end_i]['type']
                if ntype == 'data':
                    end_i += 1
                else:
                    break
            size = (end_i - i) * SECTOR
            regions.append({
                'offset': start,
                'size': size,
                'content_type': 'app',
                'details': s['details'],
            })
            i = end_i
            continue

        # NVS: consecutive NVS pages
        if stype == 'nvs':
            start = s['offset']
            end_i = i + 1
            while end_i < len(sector_info) and sector_info[end_i]['type'] == 'nvs':
                end_i += 1
            size = (end_i - i) * SECTOR
            regions.append({
                'offset': start,
                'size': size,
                'content_type': 'nvs',
                'details': {'page_count': end_i - i},
            })
            i = end_i
            continue

        # OTA data: consecutive OTA sectors (typically 2)
        if stype == 'ota_data':
            start = s['offset']
            end_i = i + 1
            while end_i < len(sector_info) and sector_info[end_i]['type'] == 'ota_data':
                end_i += 1
            size = (end_i - i) * SECTOR
            regions.append({
                'offset': start,
                'size': size,
                'content_type': 'ota_data',
                'details': s['details'],
            })
            i = end_i
            continue

        # PHY: single sector (or consecutive PHY sectors)
        if stype == 'phy':
            start = s['offset']
            end_i = i + 1
            while end_i < len(sector_info) and sector_info[end_i]['type'] == 'phy':
                end_i += 1
            size = (end_i - i) * SECTOR
            regions.append({
                'offset': start,
                'size': size,
                'content_type': 'phy',
                'details': {},
            })
            i = end_i
            continue

        # Standalone 'data' sectors not preceded by app header
        i += 1

    return {
        'flash_size': flash_size,
        'regions': regions,
    }


def parse_partial_pt(flash_data):
    """Extract any intact partition table entries from the PT region.

    Handles partially-corrupted partition tables where some entries are
    valid (have correct magic bytes) and others are zeroed/corrupted.
    """
    pt_region = flash_data[PT_OFFSET:PT_OFFSET + PT_SIZE]
    entries = []

    for offset in range(0, MAX_PT_DATA, PT_ENTRY_SIZE):
        chunk = pt_region[offset:offset + PT_ENTRY_SIZE]
        if len(chunk) != PT_ENTRY_SIZE:
            break

        # End marker
        if chunk == b'\xFF' * PT_ENTRY_SIZE:
            break

        # MD5 marker
        if chunk[:2] == b'\xeb\xeb':
            break

        # Zeroed entry (corrupted)
        if chunk == b'\x00' * PT_ENTRY_SIZE:
            continue

        # Valid entry
        if chunk[:2] == PT_MAGIC:
            magic, ptype, subtype, pt_offset, size, name_bytes, flags = \
                struct.unpack(PT_STRUCT, chunk)
            name = name_bytes.split(b'\x00')[0].decode('ascii', errors='replace')
            entries.append({
                'name': name,
                'type': ptype,
                'subtype': subtype,
                'offset': pt_offset,
                'size': size,
                'flags': flags,
            })

    return entries


def reconstruct_pt(filepath, output_path):
    """Reconstruct a valid partition table binary from a flash dump.

    Algorithm:
    1. Parse any surviving entries from the partial partition table
    2. Scan flash for content regions
    3. Filter to partition-relevant regions (offset >= PT_OFFSET + PT_SIZE)
    4. Infer OTA vs factory layout from presence of OTA data
    5. Merge surviving PT entries with scan-detected regions (no duplicates)
    6. Assign names, types, and subtypes per ESP-IDF conventions
    7. Validate alignment and size constraints
    8. Generate binary with correct magic bytes and MD5 checksum
    """
    with open(filepath, 'rb') as f:
        flash = f.read()

    # Step 1: Parse surviving PT entries
    existing_entries = parse_partial_pt(flash)
    existing_offsets = {e['offset'] for e in existing_entries}

    # Step 2: Scan flash content
    scan_result = scan_flash(filepath)
    regions = scan_result['regions']

    # Step 3: Filter to regions after the partition table
    min_offset = PT_OFFSET + PT_SIZE  # 0x9000
    regions = [r for r in regions if r['offset'] >= min_offset]

    # Step 4: Build entries from scan results, skipping already-known offsets
    new_entries = []
    app_count = 0  # Track APP partitions for naming

    # Count existing APP entries to offset the naming counter
    for e in existing_entries:
        if e['type'] == APP_TYPE:
            app_count += 1

    for region in regions:
        if region['offset'] in existing_offsets:
            continue

        offset = region['offset']
        size = region['size']
        ctype = region['content_type']

        if ctype == 'nvs':
            new_entries.append({
                'name': 'nvs',
                'type': DATA_TYPE,
                'subtype': 0x02,
                'offset': offset,
                'size': size,
                'flags': 0,
            })
        elif ctype == 'ota_data':
            new_entries.append({
                'name': 'otadata',
                'type': DATA_TYPE,
                'subtype': 0x00,
                'offset': offset,
                'size': size,
                'flags': 0,
            })
        elif ctype == 'phy':
            new_entries.append({
                'name': 'phy_init',
                'type': DATA_TYPE,
                'subtype': 0x01,
                'offset': offset,
                'size': size,
                'flags': 0,
            })
        elif ctype == 'app':
            if app_count == 0:
                name = 'factory'
                subtype = 0x00
            else:
                name = f'ota_{app_count - 1}'
                subtype = 0x10 + (app_count - 1)
            new_entries.append({
                'name': name,
                'type': APP_TYPE,
                'subtype': subtype,
                'offset': offset,
                'size': size,
                'flags': 0,
            })
            app_count += 1

    # Step 5: Merge and sort by offset
    all_entries = list(existing_entries) + new_entries
    all_entries.sort(key=lambda e: e['offset'])

    # Step 6: Validate and fix constraints
    for entry in all_entries:
        if entry['type'] == APP_TYPE:
            # 64KB offset alignment
            if entry['offset'] % APP_OFFSET_ALIGN != 0:
                entry['offset'] = ((entry['offset'] + APP_OFFSET_ALIGN - 1)
                                   // APP_OFFSET_ALIGN * APP_OFFSET_ALIGN)
            # 4KB size alignment
            if entry['size'] % APP_SIZE_ALIGN != 0:
                entry['size'] = ((entry['size'] + APP_SIZE_ALIGN - 1)
                                 // APP_SIZE_ALIGN * APP_SIZE_ALIGN)
        else:
            # 4KB offset alignment for data partitions
            if entry['offset'] % DATA_OFFSET_ALIGN != 0:
                entry['offset'] = ((entry['offset'] + DATA_OFFSET_ALIGN - 1)
                                   // DATA_OFFSET_ALIGN * DATA_OFFSET_ALIGN)

    # Step 7: Build partition table binary
    pt_data = b''
    for entry in all_entries:
        name_bytes = entry['name'].encode('ascii')[:16].ljust(16, b'\x00')
        pt_data += struct.pack(
            PT_STRUCT,
            PT_MAGIC,
            entry['type'],
            entry['subtype'],
            entry['offset'],
            entry['size'],
            name_bytes,
            entry['flags'],
        )

    # Append MD5 marker + digest
    md5_digest = hashlib.md5(pt_data).digest()
    pt_data += MD5_MARKER + md5_digest

    # Pad to 0xC00
    pt_data += b'\xFF' * (MAX_PT_DATA - len(pt_data))

    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(pt_data)


def check_pt(filepath):
    """Parse and validate a partition table binary.

    Returns a dict with 'entries', 'md5', and 'issues'.
    """
    with open(filepath, 'rb') as f:
        data = f.read()

    entries = []
    raw_entry_data = b''
    md5_info = {'present': False, 'valid': None}
    issues = []

    # Parse entries
    for offset in range(0, min(len(data), MAX_PT_DATA), PT_ENTRY_SIZE):
        chunk = data[offset:offset + PT_ENTRY_SIZE]
        if len(chunk) != PT_ENTRY_SIZE:
            break

        if chunk == b'\xFF' * PT_ENTRY_SIZE:
            break

        if chunk[:2] == b'\xeb\xeb':
            md5_info['present'] = True
            expected = hashlib.md5(raw_entry_data).digest()
            md5_info['valid'] = (expected == chunk[16:])
            continue

        magic, ptype, subtype, pt_offset, size, name_bytes, flags = \
            struct.unpack(PT_STRUCT, chunk)
        name = name_bytes.split(b'\x00')[0].decode('ascii', errors='replace')
        valid_magic = (magic == PT_MAGIC)

        entry = {
            'index': len(entries),
            'name': name,
            'type': ptype,
            'subtype': subtype,
            'offset': pt_offset,
            'size': size,
            'flags': flags,
            'valid_magic': valid_magic,
        }
        entries.append(entry)
        raw_entry_data += chunk

    # --- Validation checks ---

    for entry in entries:
        idx = entry['index']

        # Invalid magic
        if not entry['valid_magic']:
            issues.append({
                'entry_index': idx,
                'issue_type': 'invalid_magic',
                'description': f"Entry '{entry['name']}' has invalid magic bytes",
            })

        # Offset alignment
        if entry['type'] == APP_TYPE:
            if entry['offset'] % APP_OFFSET_ALIGN != 0:
                issues.append({
                    'entry_index': idx,
                    'issue_type': 'offset_not_aligned',
                    'description': (
                        f"APP '{entry['name']}' offset 0x{entry['offset']:x} "
                        f"not aligned to 0x{APP_OFFSET_ALIGN:x}"
                    ),
                })
            # APP size alignment
            if entry['size'] % APP_SIZE_ALIGN != 0:
                issues.append({
                    'entry_index': idx,
                    'issue_type': 'app_size_not_aligned',
                    'description': (
                        f"APP '{entry['name']}' size 0x{entry['size']:x} "
                        f"not aligned to 0x{APP_SIZE_ALIGN:x}"
                    ),
                })
        elif entry['type'] == DATA_TYPE:
            if entry['offset'] % DATA_OFFSET_ALIGN != 0:
                issues.append({
                    'entry_index': idx,
                    'issue_type': 'offset_not_aligned',
                    'description': (
                        f"DATA '{entry['name']}' offset 0x{entry['offset']:x} "
                        f"not aligned to 0x{DATA_OFFSET_ALIGN:x}"
                    ),
                })

        # NVS minimum size
        if entry['type'] == DATA_TYPE and entry['subtype'] == 0x02:
            is_readonly = bool(entry['flags'] & 0x02)
            if not is_readonly and entry['size'] < NVS_MIN_SIZE:
                issues.append({
                    'entry_index': idx,
                    'issue_type': 'nvs_too_small',
                    'description': (
                        f"NVS '{entry['name']}' size 0x{entry['size']:x} "
                        f"below minimum 0x{NVS_MIN_SIZE:x}"
                    ),
                })

        # OTA data exact size
        if entry['type'] == DATA_TYPE and entry['subtype'] == 0x00:
            if entry['size'] != OTA_DATA_SIZE:
                issues.append({
                    'entry_index': idx,
                    'issue_type': 'otadata_wrong_size',
                    'description': (
                        f"OTA data '{entry['name']}' size 0x{entry['size']:x} "
                        f"must be exactly 0x{OTA_DATA_SIZE:x}"
                    ),
                })

        # Unknown flags
        if entry['flags'] & ~KNOWN_FLAG_MASK:
            unknown = entry['flags'] & ~KNOWN_FLAG_MASK
            issues.append({
                'entry_index': idx,
                'issue_type': 'unknown_flags',
                'description': f"Unknown flag bits: 0x{unknown:08x}",
            })

    # Duplicate names
    seen_names = {}
    for entry in entries:
        if entry['name'] in seen_names:
            issues.append({
                'entry_index': entry['index'],
                'issue_type': 'duplicate_name',
                'description': (
                    f"Duplicate name '{entry['name']}' "
                    f"(first at index {seen_names[entry['name']]})"
                ),
            })
        else:
            seen_names[entry['name']] = entry['index']

    # Overlapping partitions
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
                    f"'{nxt['name']}' at 0x{nxt['offset']:x} overlaps "
                    f"'{curr['name']}' ending at 0x{curr_end:x}"
                ),
            })

    # MD5 integrity
    if md5_info['present'] and not md5_info['valid']:
        issues.append({
            'issue_type': 'invalid_md5',
            'description': 'MD5 checksum mismatch',
        })

    return {
        'entries': entries,
        'md5': md5_info,
        'issues': issues,
    }


def main():
    parser = argparse.ArgumentParser(
        description='ESP-IDF Flash Forensics Tool'
    )
    sub = parser.add_subparsers(dest='command', required=True)

    p_scan = sub.add_parser('scan', help='Scan flash dump for content regions')
    p_scan.add_argument('flash_dump', help='Path to flash dump file')

    p_recon = sub.add_parser('reconstruct',
                              help='Reconstruct partition table from flash dump')
    p_recon.add_argument('flash_dump', help='Path to flash dump file')
    p_recon.add_argument('output_file', help='Output partition table binary path')

    p_check = sub.add_parser('check',
                              help='Validate a partition table binary')
    p_check.add_argument('ptable_binary', help='Path to partition table binary')

    args = parser.parse_args()

    if args.command == 'scan':
        result = scan_flash(args.flash_dump)
        print(json.dumps(result, indent=2))

    elif args.command == 'reconstruct':
        reconstruct_pt(args.flash_dump, args.output_file)
        print(json.dumps({'status': 'success', 'output': args.output_file}))

    elif args.command == 'check':
        result = check_pt(args.ptable_binary)
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
