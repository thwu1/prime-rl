#!/usr/bin/env python3
"""Generate Kafka cluster metadata and partition log binary fixtures.

Creates the directory structure and binary log files that a Kafka broker
reads at startup to discover topics, partitions, and stored messages.

Directory layout created:
  /data/kraft-combined-logs/
    __cluster_metadata-0/00000000000000000000.log   (cluster metadata)
    __cluster_metadata-0/partition.metadata
    alpha-0/00000000000000000000.log                (2 RecordBatches)
    alpha-0/partition.metadata
    alpha-1/00000000000000000000.log                (empty)
    alpha-1/partition.metadata
    beta-0/00000000000000000000.log                 (1 RecordBatch)
    beta-0/partition.metadata

Binary encoding reference (all integers big-endian):
  - INT8/16/32/64: fixed-width signed big-endian
  - Unsigned varint (uvarint): LEB128
  - Signed varint: zigzag + LEB128
  - Compact string: uvarint(len+1) + bytes
  - Compact array: uvarint(count+1) + elements
  - UUID: 16 raw bytes
  - RecordBatch: BaseOffset(I64) BatchLength(I32) PartitionLeaderEpoch(I32)
                 Magic(I8=2) CRC32C(U32) Properties...
  - CRC32-Castagnoli covers: Attributes through end of all Records
"""

import struct
import os
import crcmod

# ─── Constants ───────────────────────────────────────────────────────────
KRAFT_LOG_DIR = "/data/kraft-combined-logs"

ALPHA_UUID = "00112233-4455-6677-8899-aabbccddeeff"
BETA_UUID  = "a0b1c2d3-e4f5-0617-2839-4a5b6c7d8e9f"
DIR_UUID   = "d0d1d2d3-d4d5-d6d7-d8d9-dadbdcdddedf"

TIMESTAMP = 1726045943832  # fixed timestamp for reproducibility

crc32c_fn = crcmod.predefined.mkCrcFun('crc-32c')

# ─── Encoding helpers ────────────────────────────────────────────────────

def encode_int8(v):
    return struct.pack('>b', v)

def encode_int16(v):
    return struct.pack('>h', v)

def encode_int32(v):
    return struct.pack('>i', v)

def encode_int64(v):
    return struct.pack('>q', v)

def encode_uint32(v):
    return struct.pack('>I', v)

def encode_uvarint(v):
    """Unsigned LEB128."""
    buf = bytearray()
    while v > 0x7f:
        buf.append((v & 0x7f) | 0x80)
        v >>= 7
    buf.append(v & 0x7f)
    return bytes(buf)

def encode_varint(v):
    """Signed zigzag + LEB128."""
    zz = (v * 2) if v >= 0 else ((-v) * 2 - 1)
    return encode_uvarint(zz)

def encode_uuid(uuid_str):
    return bytes.fromhex(uuid_str.replace('-', ''))

def encode_compact_string(s):
    b = s.encode('utf-8')
    return encode_uvarint(len(b) + 1) + b

def encode_compact_array_int32(arr):
    result = encode_uvarint(len(arr) + 1)
    for v in arr:
        result += encode_int32(v)
    return result

# ─── Record encoding ────────────────────────────────────────────────────

def encode_record(attributes, timestamp_delta, offset_delta, key, value, headers_empty=True):
    """Encode a single Kafka Record.

    key/value: bytes or None (null).
    headers_empty: True => varint(0) (empty list), False => varint(-1) (null).
    """
    props = bytearray()
    props += encode_int8(attributes)
    props += encode_varint(timestamp_delta)
    props += encode_varint(offset_delta)

    if key is None:
        props += encode_varint(-1)
    else:
        props += encode_varint(len(key))
        props += key

    if value is None:
        props += encode_varint(-1)
    else:
        props += encode_varint(len(value))
        props += value

    # Headers
    props += encode_varint(0 if headers_empty else -1)

    size = encode_varint(len(props))
    return bytes(size) + bytes(props)


def encode_record_batch(base_offset, partition_leader_epoch, encoded_records,
                        first_ts=TIMESTAMP, max_ts=TIMESTAMP):
    """Encode a complete RecordBatch with CRC32-Castagnoli."""
    # Build properties (everything covered by CRC)
    props = bytearray()
    props += encode_int16(0)                              # attributes
    props += encode_int32(len(encoded_records) - 1)       # lastOffsetDelta
    props += encode_int64(first_ts)
    props += encode_int64(max_ts)
    props += encode_int64(-1)                             # producerId
    props += encode_int16(-1)                             # producerEpoch
    props += encode_int32(-1)                             # baseSequence
    props += encode_int32(len(encoded_records))           # recordCount
    for rec in encoded_records:
        props += rec

    crc = crc32c_fn(bytes(props))
    batch_length = len(props) + 4 + 1 + 4  # partitionLeaderEpoch + magic + CRC

    out = bytearray()
    out += encode_int64(base_offset)
    out += encode_int32(batch_length)
    out += encode_int32(partition_leader_epoch)
    out += encode_int8(2)            # magic = 2
    out += encode_uint32(crc)
    out += props
    return bytes(out)

# ─── Cluster metadata payload encoding ──────────────────────────────────

def encode_metadata_payload(frame_version, type_id, version, data_bytes):
    return encode_int8(frame_version) + encode_int8(type_id) + encode_int8(version) + data_bytes

def encode_feature_level_record():
    data = encode_compact_string("metadata.version") + encode_int16(20) + encode_uvarint(0)
    return encode_metadata_payload(1, 12, 0, data)

def encode_topic_record(name, uuid_str):
    data = encode_compact_string(name) + encode_uuid(uuid_str) + encode_uvarint(0)
    return encode_metadata_payload(1, 2, 0, data)

def encode_partition_record(partition_id, topic_uuid_str, dir_uuid_str):
    data = bytearray()
    data += encode_int32(partition_id)
    data += encode_uuid(topic_uuid_str)
    data += encode_compact_array_int32([1])     # replicas: [broker 1]
    data += encode_compact_array_int32([1])     # isr: [broker 1]
    data += encode_compact_array_int32([])      # removingReplicas: []
    data += encode_compact_array_int32([])      # addingReplicas: []
    data += encode_int32(1)                     # leader: broker 1
    data += encode_int32(0)                     # leaderEpoch
    data += encode_int32(0)                     # partitionEpoch
    data += encode_uvarint(1 + 1)              # directoryUUIDs: 1 element (compact)
    data += encode_uuid(dir_uuid_str)
    data += encode_uvarint(0)                   # tagBuffer
    return encode_metadata_payload(1, 3, 1, bytes(data))

# ─── File generators ────────────────────────────────────────────────────

def generate_cluster_metadata():
    meta_dir = os.path.join(KRAFT_LOG_DIR, "__cluster_metadata-0")
    os.makedirs(meta_dir, exist_ok=True)

    batches = bytearray()
    base_offset = 1

    # Batch 1: FeatureLevelRecord
    fl_payload = encode_feature_level_record()
    rec = encode_record(0, 0, 0, None, fl_payload, headers_empty=True)
    batches += encode_record_batch(base_offset, 1, [rec])
    base_offset += 1

    # Batch 2: Topic "alpha" + partitions 0, 1
    tr = encode_record(0, 0, 0, None, encode_topic_record("alpha", ALPHA_UUID), True)
    pr0 = encode_record(0, 0, 1, None, encode_partition_record(0, ALPHA_UUID, DIR_UUID), True)
    pr1 = encode_record(0, 0, 2, None, encode_partition_record(1, ALPHA_UUID, DIR_UUID), True)
    batches += encode_record_batch(base_offset, 1, [tr, pr0, pr1])
    base_offset += 3

    # Batch 3: Topic "beta" + partition 0
    tr2 = encode_record(0, 0, 0, None, encode_topic_record("beta", BETA_UUID), True)
    pr2 = encode_record(0, 0, 1, None, encode_partition_record(0, BETA_UUID, DIR_UUID), True)
    batches += encode_record_batch(base_offset, 1, [tr2, pr2])

    log_path = os.path.join(meta_dir, "00000000000000000000.log")
    with open(log_path, 'wb') as f:
        f.write(bytes(batches))

    meta_path = os.path.join(meta_dir, "partition.metadata")
    with open(meta_path, 'w') as f:
        f.write("version: 0\ntopic_id: 00000000-0000-4000-8000-000000000000")


def generate_partition_data():
    # alpha-0: two RecordBatches (one record each)
    _write_partition_log("alpha", 0, ALPHA_UUID, [b"hello", b"world"])

    # alpha-1: empty
    _write_partition_log("alpha", 1, ALPHA_UUID, [])

    # beta-0: one RecordBatch (one record)
    _write_partition_log("beta", 0, BETA_UUID, [b"kafka-msg"])


def _write_partition_log(topic, partition_id, topic_uuid, messages):
    d = os.path.join(KRAFT_LOG_DIR, f"{topic}-{partition_id}")
    os.makedirs(d, exist_ok=True)

    log_data = bytearray()
    for i, msg in enumerate(messages):
        rec = encode_record(0, 0, 0, None, msg, headers_empty=True)
        log_data += encode_record_batch(i, 1, [rec])

    with open(os.path.join(d, "00000000000000000000.log"), 'wb') as f:
        f.write(bytes(log_data))
    with open(os.path.join(d, "partition.metadata"), 'w') as f:
        f.write(f"version: 0\ntopic_id: {topic_uuid}")


# ─── Main ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    generate_cluster_metadata()
    generate_partition_data()
    print("Fixtures generated at", KRAFT_LOG_DIR)
