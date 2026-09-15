#!/usr/bin/env python3
"""Generate corrupted Kafka binary log files for the forensics task."""
import struct
import os
import gzip
import uuid as uuid_mod

# ===== CRC-32C (Castagnoli) =====

def _make_crc32c_table():
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x82F63B78
            else:
                crc >>= 1
        table.append(crc)
    return table

_CRC32C_TABLE = _make_crc32c_table()

def crc32c(data):
    crc = 0xFFFFFFFF
    for b in data:
        crc = _CRC32C_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF

# ===== Binary Encoding =====

def pack_int8(val):
    return struct.pack('>b', val)

def pack_int16(val):
    return struct.pack('>h', val)

def pack_int32(val):
    return struct.pack('>i', val)

def pack_int64(val):
    return struct.pack('>q', val)

def pack_uint32(val):
    return struct.pack('>I', val)

def pack_uuid(uuid_str):
    return uuid_mod.UUID(uuid_str).bytes

def encode_uvarint(val):
    buf = bytearray()
    while val > 0x7F:
        buf.append((val & 0x7F) | 0x80)
        val >>= 7
    buf.append(val & 0x7F)
    return bytes(buf)

def encode_svarint(val):
    if val >= 0:
        zigzag = val * 2
    else:
        zigzag = (-val) * 2 - 1
    return encode_uvarint(zigzag)

def encode_compact_string(s):
    data = s.encode('utf-8')
    return encode_uvarint(len(data) + 1) + data

def encode_compact_array_int32(values):
    result = encode_uvarint(len(values) + 1)
    for v in values:
        result += pack_int32(v)
    return result

def encode_compact_array_uuid(uuids):
    result = encode_uvarint(len(uuids) + 1)
    for u in uuids:
        result += pack_uuid(u)
    return result

# ===== Record =====

def build_record(offset_delta, timestamp_delta, key, value):
    props = bytearray()
    props += pack_int8(0)  # attributes
    props += encode_svarint(timestamp_delta)
    props += encode_svarint(offset_delta)

    if key is None:
        props += encode_svarint(-1)
    else:
        key_bytes = key.encode('utf-8') if isinstance(key, str) else key
        props += encode_svarint(len(key_bytes))
        props += key_bytes

    if value is None:
        props += encode_svarint(-1)
    else:
        val_bytes = value.encode('utf-8') if isinstance(value, str) else value
        props += encode_svarint(len(val_bytes))
        props += val_bytes

    props += encode_svarint(0)  # headers count
    return encode_svarint(len(props)) + bytes(props)

# ===== RecordBatch =====

def build_batch(base_offset, ple, records_kv, first_ts=1700000000000,
                compress=None, producer_id=-1, producer_epoch=-1, base_seq=-1):
    n = len(records_kv)
    records_bytes = b''
    for i, (k, v) in enumerate(records_kv):
        records_bytes += build_record(i, i * 100, k, v)

    last_od = max(n - 1, 0)
    max_ts = first_ts + (n - 1) * 100 if n > 1 else first_ts

    # Compress records if requested
    if compress == 'gzip':
        final_records = gzip.compress(records_bytes)
        attributes = 1  # gzip codec in bits 0-2
    else:
        final_records = records_bytes
        attributes = 0  # no compression

    props = bytearray()
    props += pack_int16(attributes)   # attributes
    props += pack_int32(last_od)      # last_offset_delta
    props += pack_int64(first_ts)     # first_timestamp
    props += pack_int64(max_ts)       # max_timestamp
    props += pack_int64(producer_id)  # producer_id
    props += pack_int16(producer_epoch)  # producer_epoch
    props += pack_int32(base_seq)     # base_sequence
    props += pack_int32(n)            # num_records
    props += final_records

    crc_val = crc32c(props)
    batch_len = len(props) + 4 + 1 + 4  # PLE + Magic + CRC

    batch = bytearray()
    batch += pack_int64(base_offset)
    batch += pack_int32(batch_len)
    batch += pack_int32(ple)
    batch += pack_int8(2)  # magic
    batch += pack_uint32(crc_val)
    batch += props
    return bytes(batch)

# ===== Cluster Metadata Payloads =====

def encode_feature_level(name, level):
    p = bytearray()
    p += pack_int8(1)   # frame_version
    p += pack_int8(12)  # type FEATURE_LEVEL
    p += pack_int8(0)   # version
    p += encode_compact_string(name)
    p += pack_int16(level)
    p += encode_uvarint(0)
    return bytes(p)

def encode_topic_record(topic_name, topic_uuid):
    p = bytearray()
    p += pack_int8(1)   # frame_version
    p += pack_int8(2)   # type TOPIC_RECORD
    p += pack_int8(0)   # version
    p += encode_compact_string(topic_name)
    p += pack_uuid(topic_uuid)
    p += encode_uvarint(0)
    return bytes(p)

def encode_partition_record(part_id, topic_uuid, replicas, isr,
                            leader, leader_epoch, part_epoch, dir_uuids):
    p = bytearray()
    p += pack_int8(1)   # frame_version
    p += pack_int8(3)   # type PARTITION_RECORD
    p += pack_int8(1)   # version
    p += pack_int32(part_id)
    p += pack_uuid(topic_uuid)
    p += encode_compact_array_int32(replicas)
    p += encode_compact_array_int32(isr)
    p += encode_compact_array_int32([])  # removing
    p += encode_compact_array_int32([])  # adding
    p += pack_int32(leader)
    p += pack_int32(leader_epoch)
    p += pack_int32(part_epoch)
    p += encode_compact_array_uuid(dir_uuids)
    p += encode_uvarint(0)
    return bytes(p)

# ===== Constants =====

ORDERS_UUID = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"
USERS_UUID  = "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e"
EVENTS_UUID = "c3d4e5f6-a7b8-4c9d-0e1f-2a3b4c5d6e7f"
TRADES_UUID = "e5f6a7b8-c9d0-4e1f-2a3b-4c5d6e7f8091"
DIR_UUID    = "d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f80"

BASE_DIR = "/app/kafka-data"

# ===== Data Generation =====

def gen_metadata():
    batches = []

    # Batch 0: FeatureLevel
    fl = encode_feature_level("metadata.version", 20)
    batches.append(build_batch(0, 1, [(None, fl)], 1700000000000))

    # Batch 1: orders topic + 2 partitions
    tr = encode_topic_record("orders", ORDERS_UUID)
    pr0 = encode_partition_record(0, ORDERS_UUID, [1], [1], 1, 1, 1, [DIR_UUID])
    pr1 = encode_partition_record(1, ORDERS_UUID, [1], [1], 1, 1, 1, [DIR_UUID])
    batches.append(build_batch(1, 1, [(None, tr), (None, pr0), (None, pr1)], 1700000001000))

    # Batch 2: users topic + 1 partition
    tr = encode_topic_record("users", USERS_UUID)
    pr0 = encode_partition_record(0, USERS_UUID, [1], [1], 1, 1, 1, [DIR_UUID])
    batches.append(build_batch(4, 1, [(None, tr), (None, pr0)], 1700000002000))

    # Batch 3: events topic + 3 partitions
    tr = encode_topic_record("events", EVENTS_UUID)
    pr0 = encode_partition_record(0, EVENTS_UUID, [1], [1], 1, 1, 1, [DIR_UUID])
    pr1 = encode_partition_record(1, EVENTS_UUID, [1], [1], 1, 1, 1, [DIR_UUID])
    pr2 = encode_partition_record(2, EVENTS_UUID, [1], [1], 1, 1, 1, [DIR_UUID])
    batches.append(build_batch(6, 1,
        [(None, tr), (None, pr0), (None, pr1), (None, pr2)], 1700000003000))

    # Batch 4: trades topic + 1 partition
    tr = encode_topic_record("trades", TRADES_UUID)
    pr0 = encode_partition_record(0, TRADES_UUID, [1], [1], 1, 1, 1, [DIR_UUID])
    batches.append(build_batch(10, 1, [(None, tr), (None, pr0)], 1700000004000))

    return b''.join(batches)

def gen_partition_logs():
    logs = {}

    # orders-0: VALID — 2 batches, 3 records (uncompressed)
    b0 = build_batch(0, 1, [
        ("order-001", '{"product":"laptop","qty":1,"price":999.99}'),
        ("order-002", '{"product":"mouse","qty":2,"price":29.99}'),
    ], 1700000010000)
    b1 = build_batch(2, 1, [
        ("order-003", '{"product":"keyboard","qty":1,"price":149.99}'),
    ], 1700000020000)
    logs["orders-0"] = b0 + b1

    # orders-1: CRC CORRUPTED — overwrite CRC with 0xDEADBEEF
    b0 = build_batch(0, 1, [
        ("order-004", '{"product":"monitor","qty":1,"price":499.99}'),
        ("order-005", '{"product":"webcam","qty":1,"price":79.99}'),
    ], 1700000030000)
    data = bytearray(b0)
    struct.pack_into('>I', data, 17, 0xDEADBEEF)  # CRC at offset 17
    logs["orders-1"] = bytes(data)

    # users-0: SECOND BATCH TRUNCATED — cut 20 bytes from end
    b0 = build_batch(0, 1, [
        ("user-001", '{"name":"Alice","email":"alice@example.com"}'),
        ("user-002", '{"name":"Bob","email":"bob@example.com"}'),
    ], 1700000040000)
    b1 = build_batch(2, 1, [
        ("user-003", '{"name":"Charlie","email":"charlie@example.com"}'),
        ("user-004", '{"name":"Diana","email":"diana@example.com"}'),
    ], 1700000050000)
    logs["users-0"] = (b0 + b1)[:-20]

    # events-0: WRONG BASE OFFSET on batch 2 — set to 0 instead of 3
    b0 = build_batch(0, 1, [
        ("evt-001", '{"type":"click","page":"/home"}'),
        ("evt-002", '{"type":"view","page":"/products"}'),
        ("evt-003", '{"type":"click","page":"/products/1"}'),
    ], 1700000060000)
    b1 = build_batch(3, 1, [
        ("evt-004", '{"type":"purchase","page":"/checkout"}'),
        ("evt-005", '{"type":"view","page":"/confirmation"}'),
    ], 1700000070000)
    b1_bad = bytearray(b1)
    struct.pack_into('>q', b1_bad, 0, 0)  # BaseOffset to 0 (not covered by CRC)
    logs["events-0"] = b0 + bytes(b1_bad)

    # events-1: VALID — 1 batch, 1 record
    b0 = build_batch(0, 1, [
        ("evt-006", '{"type":"login","user":"alice"}'),
    ], 1700000080000)
    logs["events-1"] = b0

    # events-2: WRONG MAGIC BYTE — set to 1 instead of 2
    b0 = build_batch(0, 1, [
        ("evt-007", '{"type":"signup","user":"eve"}'),
        ("evt-008", '{"type":"verify","user":"eve"}'),
    ], 1700000090000)
    data = bytearray(b0)
    data[16] = 1  # Magic at offset 16 (not covered by CRC)
    logs["events-2"] = bytes(data)

    # trades-0: GZIP-COMPRESSED, 2 batches — batch 1 has CRC corruption
    b0 = build_batch(0, 1, [
        ("trade-001", '{"symbol":"AAPL","action":"buy","qty":100,"price":185.50}'),
        ("trade-002", '{"symbol":"GOOGL","action":"sell","qty":50,"price":141.25}'),
    ], 1700000100000, compress='gzip',
       producer_id=1001, producer_epoch=0, base_seq=0)
    b1 = build_batch(2, 1, [
        ("trade-003", '{"symbol":"MSFT","action":"buy","qty":200,"price":378.90}'),
        ("trade-004", '{"symbol":"AMZN","action":"sell","qty":75,"price":178.35}'),
    ], 1700000110000, compress='gzip',
       producer_id=1001, producer_epoch=0, base_seq=2)
    b1_bad = bytearray(b1)
    struct.pack_into('>I', b1_bad, 17, 0xBADC0DE0)  # CRC corruption
    logs["trades-0"] = b0 + bytes(b1_bad)

    return logs

def write_all():
    meta_dir = os.path.join(BASE_DIR, "__cluster_metadata-0")
    os.makedirs(meta_dir, exist_ok=True)
    with open(os.path.join(meta_dir, "00000000000000000000.log"), 'wb') as f:
        f.write(gen_metadata())

    for name, data in gen_partition_logs().items():
        d = os.path.join(BASE_DIR, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "00000000000000000000.log"), 'wb') as f:
            f.write(data)

if __name__ == "__main__":
    write_all()
    print("Generated Kafka log files with compression and corruption.")
