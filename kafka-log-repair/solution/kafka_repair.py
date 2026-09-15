#!/usr/bin/env python3
"""
Kafka RecordBatch log repair tool.
Parses binary RecordBatch format, detects corruptions, repairs files in-place,
and writes a JSON report.
"""

import struct
import os
import json
import sys

# ============================================================================
# CRC32-C (Castagnoli) — reflected lookup table
# ============================================================================

def _build_crc32c_table():
    table = []
    poly = 0x82F63B78
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
        table.append(crc)
    return table

_CRC32C_TABLE = _build_crc32c_table()

def crc32c(data):
    crc = 0xFFFFFFFF
    for b in data:
        crc = _CRC32C_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF

# ============================================================================
# Zigzag varint codec
# ============================================================================

def decode_varint_signed(data, offset):
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError(f"Varint extends beyond data at offset {offset}")
        b = data[offset]
        result |= (b & 0x7F) << shift
        offset += 1
        if (b & 0x80) == 0:
            break
        shift += 7
    if result & 1:
        return -(result >> 1) - 1, offset
    else:
        return result >> 1, offset

# ============================================================================
# Record parser
# ============================================================================

def parse_record(data, offset):
    """Parse a single Record. Returns (raw_bytes, end_offset)."""
    record_start = offset
    size, offset = decode_varint_signed(data, offset)
    body_start = offset
    body_end = body_start + size
    if body_end > len(data):
        raise ValueError(f"Record body extends beyond data: need {body_end}, have {len(data)}")
    return data[record_start:body_end], body_end

# ============================================================================
# Batch parser
# ============================================================================

def parse_batch(data, offset):
    """Parse a RecordBatch. Returns (batch_info, actual_end_offset)."""
    batch_start = offset
    if offset + 61 > len(data):
        raise ValueError("Not enough data for batch header")

    base_offset = struct.unpack_from('>q', data, offset)[0]; offset += 8
    batch_length = struct.unpack_from('>i', data, offset)[0]; offset += 4
    ple = struct.unpack_from('>i', data, offset)[0]; offset += 4
    magic = data[offset]; offset += 1
    stored_crc = struct.unpack_from('>I', data, offset)[0]; offset += 4

    props_start = offset  # CRC coverage starts here

    attributes = struct.unpack_from('>h', data, offset)[0]; offset += 2
    last_offset_delta = struct.unpack_from('>i', data, offset)[0]; offset += 4
    first_timestamp = struct.unpack_from('>q', data, offset)[0]; offset += 8
    max_timestamp = struct.unpack_from('>q', data, offset)[0]; offset += 8
    producer_id = struct.unpack_from('>q', data, offset)[0]; offset += 8
    producer_epoch = struct.unpack_from('>h', data, offset)[0]; offset += 2
    base_sequence = struct.unpack_from('>i', data, offset)[0]; offset += 4
    record_count = struct.unpack_from('>i', data, offset)[0]; offset += 4

    expected_end = batch_start + 12 + batch_length

    # Parse records — may stop early if data runs out
    records_raw = []
    actual_record_count = 0
    for _ in range(record_count):
        if offset >= expected_end or offset >= len(data):
            break
        try:
            raw, offset = parse_record(data, offset)
            records_raw.append(raw)
            actual_record_count += 1
        except (ValueError, IndexError, struct.error):
            break

    actual_batch_end = offset
    actual_batch_length = actual_batch_end - batch_start - 12

    # --- Detect corruptions ---
    corruptions = []

    if magic != 2:
        corruptions.append({
            'type': 'invalid_magic',
            'details': f'Magic byte is {magic}, expected 2',
        })

    if batch_length != actual_batch_length:
        corruptions.append({
            'type': 'invalid_batch_length',
            'details': (f'BatchLength field is {batch_length}, '
                        f'actual data size is {actual_batch_length}'),
        })

    if record_count != actual_record_count:
        corruptions.append({
            'type': 'invalid_record_count',
            'details': (f'RecordCount field is {record_count}, '
                        f'actual records found: {actual_record_count}'),
        })

    if first_timestamp > max_timestamp:
        corruptions.append({
            'type': 'invalid_timestamps',
            'details': (f'FirstTimestamp ({first_timestamp}) > '
                        f'MaxTimestamp ({max_timestamp})'),
        })

    # Check CRC against current raw properties (only flag if no other corruption
    # altered the CRC-covered region, so it's a standalone CRC issue)
    current_props = data[props_start:actual_batch_end]
    current_crc = crc32c(current_props)
    if stored_crc != current_crc:
        # Only report as invalid_crc if no other corruption would explain the
        # CRC mismatch (record_count and timestamps are in the CRC region)
        crc_region_corruptions = [c for c in corruptions
                                  if c['type'] in ('invalid_record_count',
                                                   'invalid_timestamps')]
        if not crc_region_corruptions:
            corruptions.append({
                'type': 'invalid_crc',
                'details': (f'CRC field 0x{stored_crc:08X} does not match '
                            f'computed CRC 0x{current_crc:08X}'),
            })

    return {
        'batch_start': batch_start,
        'props_start': props_start,
        'batch_end': actual_batch_end,
        'magic': magic,
        'batch_length': batch_length,
        'actual_batch_length': actual_batch_length,
        'first_timestamp': first_timestamp,
        'max_timestamp': max_timestamp,
        'record_count': record_count,
        'actual_record_count': actual_record_count,
        'records_raw': records_raw,
        'corruptions': corruptions,
    }, actual_batch_end

# ============================================================================
# Batch repair
# ============================================================================

def repair_batch(data, info):
    """Apply repairs to a batch in data (bytearray). Returns modified data."""
    data = bytearray(data)
    bs = info['batch_start']

    for c in info['corruptions']:
        ct = c['type']
        if ct == 'invalid_magic':
            data[bs + 16] = 2

        elif ct == 'invalid_batch_length':
            struct.pack_into('>i', data, bs + 8, info['actual_batch_length'])

        elif ct == 'invalid_record_count':
            # RecordCount is at props_start + 36
            # (attrs=2 + lod=4 + ft=8 + mt=8 + pid=8 + pe=2 + bs=4 = 36)
            rc_offset = info['props_start'] + 36
            struct.pack_into('>i', data, rc_offset, info['actual_record_count'])

        elif ct == 'invalid_timestamps':
            ft_offset = info['props_start'] + 6   # attrs(2) + lod(4)
            mt_offset = ft_offset + 8
            # Swap back: write the smaller as first, larger as max
            ft = min(info['first_timestamp'], info['max_timestamp'])
            mt = max(info['first_timestamp'], info['max_timestamp'])
            struct.pack_into('>q', data, ft_offset, ft)
            struct.pack_into('>q', data, mt_offset, mt)

    # Recompute CRC over the (now-corrected) properties region
    props_data = bytes(data[info['props_start']:info['batch_end']])
    new_crc = crc32c(props_data)
    struct.pack_into('>I', data, bs + 17, new_crc)

    return bytes(data)

# ============================================================================
# Main
# ============================================================================

def process_file(filepath, partition_name):
    with open(filepath, 'rb') as f:
        data = f.read()

    batches = []
    corruptions_report = []
    offset = 0
    batch_idx = 0

    while offset < len(data):
        try:
            info, offset = parse_batch(data, offset)
            batches.append(info)
            for c in info['corruptions']:
                corruptions_report.append({
                    'file': f'{partition_name}/00000000000000000000.log',
                    'batch_index': batch_idx,
                    'type': c['type'],
                    'details': c['details'],
                })
            batch_idx += 1
        except (ValueError, struct.error) as e:
            print(f"Error parsing batch {batch_idx} in {filepath}: {e}",
                  file=sys.stderr)
            break

    repaired = data
    for info in batches:
        if info['corruptions']:
            repaired = repair_batch(repaired, info)

    if repaired != data:
        with open(filepath, 'wb') as f:
            f.write(repaired)
        print(f"Repaired: {filepath}")
    else:
        print(f"Clean:    {filepath}")

    return corruptions_report


def main():
    data_dir = '/app/data'
    manifest_path = os.path.join(data_dir, 'manifest.json')
    with open(manifest_path) as f:
        manifest = json.load(f)

    all_corruptions = []
    for name in sorted(manifest['partitions'].keys()):
        log_path = os.path.join(data_dir, name, '00000000000000000000.log')
        if not os.path.exists(log_path):
            print(f"Warning: {log_path} not found", file=sys.stderr)
            continue
        all_corruptions.extend(process_file(log_path, name))

    report = {'corruptions': all_corruptions}
    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\nReport: /app/report.json ({len(all_corruptions)} corruptions)")


if __name__ == '__main__':
    main()
