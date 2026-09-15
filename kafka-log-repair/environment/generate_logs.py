#!/usr/bin/env python3
"""
Generate corrupted Kafka RecordBatch log files for the repair task.
Creates partition log directories with intentional corruptions.
"""

import struct
import os
import json

# ============================================================================
# CRC32-C (Castagnoli) — reflected lookup table implementation
# Polynomial: 0x1EDC6F41 (normal), 0x82F63B78 (reflected)
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

# Self-test
assert crc32c(b"123456789") == 0xE3069283, "CRC32-C self-test failed"

# ============================================================================
# Zigzag varint encoding (signed)
# ============================================================================

def encode_varint_signed(value):
    if value >= 0:
        zigzag = value << 1
    else:
        zigzag = ((-value) << 1) - 1
    result = bytearray()
    while zigzag > 0x7F:
        result.append((zigzag & 0x7F) | 0x80)
        zigzag >>= 7
    result.append(zigzag & 0x7F)
    return bytes(result)

# ============================================================================
# Record encoding
# ============================================================================

def encode_record(offset_delta, timestamp_delta, key, value):
    body = bytearray()
    body.append(0)  # attributes int8
    body.extend(encode_varint_signed(timestamp_delta))
    body.extend(encode_varint_signed(offset_delta))
    if key is None:
        body.extend(encode_varint_signed(-1))
    else:
        if isinstance(key, str):
            key = key.encode('utf-8')
        body.extend(encode_varint_signed(len(key)))
        body.extend(key)
    if value is None:
        body.extend(encode_varint_signed(-1))
    else:
        if isinstance(value, str):
            value = value.encode('utf-8')
        body.extend(encode_varint_signed(len(value)))
        body.extend(value)
    body.extend(encode_varint_signed(0))  # header count
    record = bytearray()
    record.extend(encode_varint_signed(len(body)))
    record.extend(body)
    return bytes(record)

# ============================================================================
# RecordBatch encoding
# ============================================================================

def encode_properties(attributes, last_offset_delta, first_timestamp,
                      max_timestamp, producer_id, producer_epoch,
                      base_sequence, record_count, encoded_records):
    props = bytearray()
    props.extend(struct.pack('>h', attributes))
    props.extend(struct.pack('>i', last_offset_delta))
    props.extend(struct.pack('>q', first_timestamp))
    props.extend(struct.pack('>q', max_timestamp))
    props.extend(struct.pack('>q', producer_id))
    props.extend(struct.pack('>h', producer_epoch))
    props.extend(struct.pack('>i', base_sequence))
    props.extend(struct.pack('>i', record_count))
    for rec in encoded_records:
        props.extend(rec)
    return bytes(props)


def encode_record_batch(base_offset, encoded_records, first_timestamp=1000000,
                        max_timestamp=None, partition_leader_epoch=1):
    if max_timestamp is None:
        max_timestamp = first_timestamp + (len(encoded_records) - 1) * 100
    last_offset_delta = len(encoded_records) - 1
    props = encode_properties(0, last_offset_delta, first_timestamp,
                              max_timestamp, -1, -1, -1,
                              len(encoded_records), encoded_records)
    crc = crc32c(props)
    batch_length = 4 + 1 + 4 + len(props)
    batch = bytearray()
    batch.extend(struct.pack('>q', base_offset))
    batch.extend(struct.pack('>i', batch_length))
    batch.extend(struct.pack('>i', partition_leader_epoch))
    batch.append(2)
    batch.extend(struct.pack('>I', crc))
    batch.extend(props)
    return bytes(batch)


def encode_record_batch_raw(base_offset, encoded_records, first_timestamp=1000000,
                            max_timestamp=None, partition_leader_epoch=1,
                            magic=2, override_crc=None,
                            override_batch_length=None,
                            override_record_count=None,
                            swap_timestamps=False):
    if max_timestamp is None:
        max_timestamp = first_timestamp + (len(encoded_records) - 1) * 100
    if swap_timestamps:
        first_timestamp, max_timestamp = max_timestamp, first_timestamp
    last_offset_delta = len(encoded_records) - 1
    record_count = override_record_count if override_record_count is not None else len(encoded_records)
    props = encode_properties(0, last_offset_delta, first_timestamp,
                              max_timestamp, -1, -1, -1,
                              record_count, encoded_records)
    crc = override_crc if override_crc is not None else crc32c(props)
    batch_length = 4 + 1 + 4 + len(props)
    if override_batch_length is not None:
        batch_length = override_batch_length
    batch = bytearray()
    batch.extend(struct.pack('>q', base_offset))
    batch.extend(struct.pack('>i', batch_length))
    batch.extend(struct.pack('>i', partition_leader_epoch))
    batch.append(magic)
    batch.extend(struct.pack('>I', crc))
    batch.extend(props)
    return bytes(batch)


# ============================================================================
# Generate all corrupted log files
# ============================================================================

def write_log(directory, data):
    os.makedirs(directory, exist_ok=True)
    filepath = os.path.join(directory, '00000000000000000000.log')
    with open(filepath, 'wb') as f:
        f.write(data)
    return filepath


def generate():
    base_dir = '/app/data'
    os.makedirs(base_dir, exist_ok=True)

    # --- orders-0: Wrong CRC (set to 0xDEADBEEF) ---
    records_o0 = [
        encode_record(0, 0, "order-id", "order-1001: laptop, qty=2"),
        encode_record(1, 100, "order-id", "order-1002: keyboard, qty=5"),
        encode_record(2, 200, "order-id", "order-1003: monitor, qty=1"),
    ]
    batch_o0 = encode_record_batch_raw(
        base_offset=0, encoded_records=records_o0,
        first_timestamp=1700000000000, max_timestamp=1700000000200,
        override_crc=0xDEADBEEF,
    )
    write_log(os.path.join(base_dir, 'orders-0'), batch_o0)

    # --- orders-1: BatchLength is 10 too large ---
    records_o1 = [
        encode_record(0, 0, "order-id", "order-2001: mouse, qty=10"),
        encode_record(1, 100, "order-id", "order-2002: cable, qty=20"),
    ]
    correct_batch_o1 = encode_record_batch(
        base_offset=0, encoded_records=records_o1,
        first_timestamp=1700000100000, max_timestamp=1700000100100,
    )
    correct_bl = struct.unpack('>i', correct_batch_o1[8:12])[0]
    batch_o1 = encode_record_batch_raw(
        base_offset=0, encoded_records=records_o1,
        first_timestamp=1700000100000, max_timestamp=1700000100100,
        override_batch_length=correct_bl + 10,
    )
    write_log(os.path.join(base_dir, 'orders-1'), batch_o1)

    # --- events-0: Two batches, second has magic=1 ---
    records_e0_b1 = [
        encode_record(0, 0, "event-type", "user.login: alice"),
        encode_record(1, 100, "event-type", "user.login: bob"),
    ]
    records_e0_b2 = [
        encode_record(0, 0, "event-type", "user.logout: alice"),
        encode_record(1, 100, "event-type", "user.purchase: bob"),
    ]
    batch_e0_1 = encode_record_batch(
        base_offset=0, encoded_records=records_e0_b1,
        first_timestamp=1700000200000, max_timestamp=1700000200100,
    )
    batch_e0_2 = encode_record_batch_raw(
        base_offset=2, encoded_records=records_e0_b2,
        first_timestamp=1700000200200, max_timestamp=1700000200300,
        magic=1,
    )
    write_log(os.path.join(base_dir, 'events-0'), batch_e0_1 + batch_e0_2)

    # --- events-1: RecordCount says 5 but only 3 records exist ---
    records_e1 = [
        encode_record(0, 0, "page", "page.view: /home"),
        encode_record(1, 100, "page", "page.view: /products"),
        encode_record(2, 200, "page", "page.view: /checkout"),
    ]
    batch_e1 = encode_record_batch_raw(
        base_offset=0, encoded_records=records_e1,
        first_timestamp=1700000300000, max_timestamp=1700000300200,
        override_record_count=5,
    )
    write_log(os.path.join(base_dir, 'events-1'), batch_e1)

    # --- metrics-0: FirstTimestamp and MaxTimestamp swapped ---
    records_m0 = [
        encode_record(0, 0, "metric", "cpu.usage: 78.5"),
        encode_record(1, 100, "metric", "memory.usage: 62.3"),
    ]
    batch_m0 = encode_record_batch_raw(
        base_offset=0, encoded_records=records_m0,
        first_timestamp=1700000400000, max_timestamp=1700000400100,
        swap_timestamps=True,
    )
    write_log(os.path.join(base_dir, 'metrics-0'), batch_m0)

    # --- Manifest ---
    manifest = {
        "partitions": {
            "orders-0": {"expected_batches": 1, "expected_total_records": 3},
            "orders-1": {"expected_batches": 1, "expected_total_records": 2},
            "events-0": {"expected_batches": 2, "expected_total_records": 4},
            "events-1": {"expected_batches": 1, "expected_total_records": 3},
            "metrics-0": {"expected_batches": 1, "expected_total_records": 2},
        }
    }
    with open(os.path.join(base_dir, 'manifest.json'), 'w') as f:
        json.dump(manifest, f, indent=2)

    print("Generated corrupted Kafka log files successfully.")


if __name__ == '__main__':
    generate()
