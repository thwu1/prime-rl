#!/usr/bin/env python3
"""Generate Kafka KRaft data directory with controlled corruptions."""

import struct
import json
import os

# === CRC32-Castagnoli (polynomial 0x82F63B78 reflected) ===

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


# === Binary Encoder ===

class Encoder:
    def __init__(self):
        self._buf = bytearray()

    def write_int8(self, v):
        self._buf += struct.pack('>b', v)

    def write_int16(self, v):
        self._buf += struct.pack('>h', v)

    def write_int32(self, v):
        self._buf += struct.pack('>i', v)

    def write_uint32(self, v):
        self._buf += struct.pack('>I', v & 0xFFFFFFFF)

    def write_int64(self, v):
        self._buf += struct.pack('>q', v)

    def write_raw(self, data):
        self._buf += data

    def write_varint(self, v):
        if v >= 0:
            zigzag = v * 2
        else:
            zigzag = (-v - 1) * 2 + 1
        self._write_uvarint(zigzag)

    def write_uvarint(self, v):
        self._write_uvarint(v)

    def _write_uvarint(self, v):
        while v > 0x7F:
            self._buf.append((v & 0x7F) | 0x80)
            v >>= 7
        self._buf.append(v & 0x7F)

    def write_compact_string(self, s):
        data = s.encode('utf-8')
        self.write_uvarint(len(data) + 1)
        self.write_raw(data)

    def write_compact_array_int32(self, arr):
        self.write_uvarint(len(arr) + 1)
        for v in arr:
            self.write_int32(v)

    def write_uuid(self, uuid_bytes):
        assert len(uuid_bytes) == 16
        self.write_raw(uuid_bytes)

    def bytes(self):
        return bytes(self._buf)


# === Record Encoding ===

def encode_record(attributes, timestamp_delta, offset_delta, key, value):
    props = Encoder()
    props.write_int8(attributes)
    props.write_varint(timestamp_delta)
    props.write_varint(offset_delta)
    if key is None:
        props.write_varint(-1)
    else:
        props.write_varint(len(key))
        props.write_raw(key)
    if value is None:
        props.write_varint(-1)
    else:
        props.write_varint(len(value))
        props.write_raw(value)
    props.write_varint(0)  # empty headers array

    props_bytes = props.bytes()
    enc = Encoder()
    enc.write_varint(len(props_bytes))
    enc.write_raw(props_bytes)
    return enc.bytes()


# === RecordBatch Encoding ===

def encode_record_batch(base_offset, partition_leader_epoch, attributes,
                        last_offset_delta, first_timestamp, max_timestamp,
                        producer_id, producer_epoch, base_sequence,
                        encoded_records):
    # Build properties (what CRC covers)
    props = Encoder()
    props.write_int16(attributes)
    props.write_int32(last_offset_delta)
    props.write_int64(first_timestamp)
    props.write_int64(max_timestamp)
    props.write_int64(producer_id)
    props.write_int16(producer_epoch)
    props.write_int32(base_sequence)
    props.write_int32(len(encoded_records))
    for rec in encoded_records:
        props.write_raw(rec)
    props_bytes = props.bytes()

    crc = crc32c(props_bytes)
    batch_length = len(props_bytes) + 9  # +4 PartitionLeaderEpoch +1 Magic +4 CRC

    enc = Encoder()
    enc.write_int64(base_offset)
    enc.write_int32(batch_length)
    enc.write_int32(partition_leader_epoch)
    enc.write_int8(2)  # Magic = 2
    enc.write_uint32(crc)
    enc.write_raw(props_bytes)
    return enc.bytes()


# === Cluster Metadata Payload Encoding ===

def encode_feature_level_record(name, feature_level):
    enc = Encoder()
    enc.write_compact_string(name)
    enc.write_int16(feature_level)
    enc.write_uvarint(0)
    return enc.bytes()

def encode_topic_record(topic_name, topic_uuid_bytes):
    enc = Encoder()
    enc.write_compact_string(topic_name)
    enc.write_uuid(topic_uuid_bytes)
    enc.write_uvarint(0)
    return enc.bytes()

def encode_partition_record(partition_id, topic_uuid_bytes, replicas, isr,
                            removing, adding, leader, leader_epoch,
                            partition_epoch, dir_uuid_list):
    enc = Encoder()
    enc.write_int32(partition_id)
    enc.write_uuid(topic_uuid_bytes)
    enc.write_compact_array_int32(replicas)
    enc.write_compact_array_int32(isr)
    enc.write_compact_array_int32(removing)
    enc.write_compact_array_int32(adding)
    enc.write_int32(leader)
    enc.write_int32(leader_epoch)
    enc.write_int32(partition_epoch)
    enc.write_uvarint(len(dir_uuid_list) + 1)
    for d in dir_uuid_list:
        enc.write_uuid(d)
    enc.write_uvarint(0)
    return enc.bytes()

def encode_metadata_payload(frame_version, type_id, version, data_bytes):
    enc = Encoder()
    enc.write_int8(frame_version)
    enc.write_int8(type_id)
    enc.write_int8(version)
    enc.write_raw(data_bytes)
    return enc.bytes()


# === Index and Checkpoint Helpers ===

def write_index_file(filepath, entries):
    """Write an offset index file. entries: list of (relative_offset, position)."""
    with open(filepath, 'wb') as f:
        for rel_offset, position in entries:
            f.write(struct.pack('>ii', rel_offset, position))


def write_leader_epoch_checkpoint(filepath, entries):
    """Write leader-epoch-checkpoint. entries: list of (epoch, start_offset)."""
    with open(filepath, 'w') as f:
        f.write("0\n")
        f.write(f"{len(entries)}\n")
        for epoch, start_offset in entries:
            f.write(f"{epoch} {start_offset}\n")


# === Constants ===

KAFKA_DATA_DIR = "/app/kafka-data"
LOG_FILE = "00000000000000000000.log"
IDX_FILE = "00000000000000000000.index"
PARTITION_META = "partition.metadata"

ALPHA_UUID = bytes.fromhex("0102030405060708090a0b0c0d0e0f10")
BETA_UUID  = bytes.fromhex("1112131415161718191a1b1c1d1e1f20")
DIR_UUID   = bytes.fromhex("aabbccddeeff00112233445566778899")
CM_TOPIC_UUID = bytes.fromhex("fffefdfcfbfaf9f8f7f6f5f4f3f2f1f0")

TIMESTAMP = 1726045943832

MESSAGES = {
    ("alpha-topic", 0): [b"alpha-p0-msg-7a3f", b"alpha-p0-msg-91bc"],
    ("alpha-topic", 1): [b"alpha-p1-msg-2d4e", b"alpha-p1-msg-6f80"],
    ("beta-topic",  0): [b"beta-p0-msg-43a1", b"beta-p0-msg-d5e7"],
    ("beta-topic",  1): [b"beta-p1-msg-8b29"],
}

LEADER_EPOCHS = {
    ("alpha-topic", 0): 1,
    ("alpha-topic", 1): 1,
    ("beta-topic",  0): 1,
    ("beta-topic",  1): 1,
}


def make_message_records(messages):
    records = []
    for i, msg in enumerate(messages):
        records.append(encode_record(0, 0, i, None, msg))
    return records


def make_message_batch(base_offset, messages):
    records = make_message_records(messages)
    return encode_record_batch(
        base_offset=base_offset,
        partition_leader_epoch=1,
        attributes=0,
        last_offset_delta=len(messages) - 1,
        first_timestamp=TIMESTAMP,
        max_timestamp=TIMESTAMP,
        producer_id=-1,
        producer_epoch=-1,
        base_sequence=-1,
        encoded_records=records,
    )


def generate_cluster_metadata(include_beta_p1):
    all_batches = bytearray()
    batch_positions = []  # (base_offset, file_position)
    base_offset = 1

    # Batch 1: FeatureLevelRecord
    fl_data = encode_feature_level_record("metadata.version", 20)
    fl_payload = encode_metadata_payload(1, 12, 0, fl_data)
    fl_record = encode_record(0, 0, 0, None, fl_payload)
    batch1 = encode_record_batch(base_offset, 1, 0, 0, TIMESTAMP, TIMESTAMP,
                                  -1, -1, -1, [fl_record])
    batch_positions.append((base_offset, len(all_batches)))
    all_batches += batch1
    base_offset += 1

    # Batch 2: alpha-topic TopicRecord + 2 PartitionRecords
    at_data = encode_topic_record("alpha-topic", ALPHA_UUID)
    at_payload = encode_metadata_payload(1, 2, 0, at_data)
    at_record = encode_record(0, 0, 0, None, at_payload)

    ap0_data = encode_partition_record(0, ALPHA_UUID, [1], [1], [], [], 1, 0, 0, [DIR_UUID])
    ap0_payload = encode_metadata_payload(1, 3, 1, ap0_data)
    ap0_record = encode_record(0, 0, 1, None, ap0_payload)

    ap1_data = encode_partition_record(1, ALPHA_UUID, [1], [1], [], [], 1, 0, 0, [DIR_UUID])
    ap1_payload = encode_metadata_payload(1, 3, 1, ap1_data)
    ap1_record = encode_record(0, 0, 2, None, ap1_payload)

    batch2 = encode_record_batch(base_offset, 1, 0, 2, TIMESTAMP + 100, TIMESTAMP + 100,
                                  -1, -1, -1, [at_record, ap0_record, ap1_record])
    batch_positions.append((base_offset, len(all_batches)))
    all_batches += batch2
    base_offset += 3

    # Batch 3: beta-topic TopicRecord + PartitionRecord(s)
    bt_data = encode_topic_record("beta-topic", BETA_UUID)
    bt_payload = encode_metadata_payload(1, 2, 0, bt_data)
    bt_record = encode_record(0, 0, 0, None, bt_payload)

    bp0_data = encode_partition_record(0, BETA_UUID, [1], [1], [], [], 1, 0, 0, [DIR_UUID])
    bp0_payload = encode_metadata_payload(1, 3, 1, bp0_data)
    bp0_record = encode_record(0, 0, 1, None, bp0_payload)

    beta_records = [bt_record, bp0_record]
    last_offset = 1

    if include_beta_p1:
        bp1_data = encode_partition_record(1, BETA_UUID, [1], [1], [], [], 1, 0, 0, [DIR_UUID])
        bp1_payload = encode_metadata_payload(1, 3, 1, bp1_data)
        bp1_record = encode_record(0, 0, 2, None, bp1_payload)
        beta_records.append(bp1_record)
        last_offset = 2

    batch3 = encode_record_batch(base_offset, 1, 0, last_offset, TIMESTAMP + 200,
                                  TIMESTAMP + 200, -1, -1, -1, beta_records)
    batch_positions.append((base_offset, len(all_batches)))
    all_batches += batch3
    return bytes(all_batches), batch_positions


def main():
    # Create directories
    topic_partitions = [
        ("alpha-topic", 0), ("alpha-topic", 1),
        ("beta-topic", 0), ("beta-topic", 1),
    ]
    uuid_map = {"alpha-topic": ALPHA_UUID, "beta-topic": BETA_UUID}

    for topic, part in topic_partitions:
        d = os.path.join(KAFKA_DATA_DIR, f"{topic}-{part}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, PARTITION_META), 'w') as f:
            f.write(f"version: 0\ntopic_id: {uuid_map[topic].hex()}")

    cm_dir = os.path.join(KAFKA_DATA_DIR, "__cluster_metadata-0")
    os.makedirs(cm_dir, exist_ok=True)
    with open(os.path.join(cm_dir, PARTITION_META), 'w') as f:
        f.write(f"version: 0\ntopic_id: {CM_TOPIC_UUID.hex()}")

    # === Cluster metadata (missing beta-topic partition 1) ===
    cm_data, cm_batch_positions = generate_cluster_metadata(include_beta_p1=False)
    with open(os.path.join(cm_dir, LOG_FILE), 'wb') as f:
        f.write(cm_data)
    # Valid index for cluster metadata
    write_index_file(os.path.join(cm_dir, IDX_FILE), cm_batch_positions)
    write_leader_epoch_checkpoint(os.path.join(cm_dir, "leader-epoch-checkpoint"), [(1, 0)])

    # === alpha-topic-0: valid log, STALE INDEX ===
    at0_batch = make_message_batch(0, MESSAGES[("alpha-topic", 0)])
    at0_dir = os.path.join(KAFKA_DATA_DIR, "alpha-topic-0")
    with open(os.path.join(at0_dir, LOG_FILE), 'wb') as f:
        f.write(at0_batch)
    # Stale index: points to byte position 999 instead of 0
    write_index_file(os.path.join(at0_dir, IDX_FILE), [(0, 999)])
    # Valid checkpoint
    write_leader_epoch_checkpoint(os.path.join(at0_dir, "leader-epoch-checkpoint"), [(1, 0)])

    # === alpha-topic-1: CRC zeroed + INVALID CHECKPOINT ===
    batch_a1 = bytearray(make_message_batch(0, MESSAGES[("alpha-topic", 1)]))
    batch_a1[17] = 0; batch_a1[18] = 0; batch_a1[19] = 0; batch_a1[20] = 0
    at1_dir = os.path.join(KAFKA_DATA_DIR, "alpha-topic-1")
    with open(os.path.join(at1_dir, LOG_FILE), 'wb') as f:
        f.write(batch_a1)
    # Valid index
    write_index_file(os.path.join(at1_dir, IDX_FILE), [(0, 0)])
    # Invalid checkpoint: epoch 99 instead of 1
    write_leader_epoch_checkpoint(os.path.join(at1_dir, "leader-epoch-checkpoint"), [(99, 0)])

    # === beta-topic-0: data corruption (byte flip in first record's value) ===
    batch_b0 = bytearray(make_message_batch(0, MESSAGES[("beta-topic", 0)]))
    target = b"beta-p0-msg-43a1"
    idx = batch_b0.find(target)
    assert idx >= 0, "Value string not found in batch bytes"
    batch_b0[idx + 5] ^= 0x42  # flip 'p' -> '2'
    bt0_dir = os.path.join(KAFKA_DATA_DIR, "beta-topic-0")
    with open(os.path.join(bt0_dir, LOG_FILE), 'wb') as f:
        f.write(batch_b0)
    # Valid index
    write_index_file(os.path.join(bt0_dir, IDX_FILE), [(0, 0)])
    # Valid checkpoint
    write_leader_epoch_checkpoint(os.path.join(bt0_dir, "leader-epoch-checkpoint"), [(1, 0)])

    # === beta-topic-1: MISSING (directory exists, no log/index/checkpoint) ===

    # === Manifest ===
    manifest = {"topics": {}}
    for topic in ["alpha-topic", "beta-topic"]:
        manifest["topics"][topic] = {
            "uuid_hex": uuid_map[topic].hex(),
            "partitions": {}
        }
    for (topic, part), msgs in MESSAGES.items():
        manifest["topics"][topic]["partitions"][str(part)] = {
            "leader_epoch": LEADER_EPOCHS[(topic, part)],
            "records": [{"key": None, "value": m.decode()} for m in msgs]
        }

    with open("/app/manifest.json", 'w') as f:
        json.dump(manifest, f, indent=2)

    print("Data generation complete.")
    for topic, part in topic_partitions:
        lp = os.path.join(KAFKA_DATA_DIR, f"{topic}-{part}", LOG_FILE)
        if os.path.exists(lp):
            print(f"  {topic}-{part}: {os.path.getsize(lp)} bytes")
        else:
            print(f"  {topic}-{part}: MISSING (intentional)")


if __name__ == "__main__":
    main()
