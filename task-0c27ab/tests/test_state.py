#!/usr/bin/env python3
"""Pytest tests for Kafka KRaft data directory recovery task."""

import struct
import json
import os
import pytest


# === CRC32-Castagnoli ===

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


# === Binary Decoder ===

class Decoder:
    def __init__(self, data):
        self.data = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        self.offset = 0

    def read_int8(self):
        v = struct.unpack_from('>b', self.data, self.offset)[0]
        self.offset += 1
        return v

    def read_int16(self):
        v = struct.unpack_from('>h', self.data, self.offset)[0]
        self.offset += 2
        return v

    def read_int32(self):
        v = struct.unpack_from('>i', self.data, self.offset)[0]
        self.offset += 4
        return v

    def read_uint32(self):
        v = struct.unpack_from('>I', self.data, self.offset)[0]
        self.offset += 4
        return v

    def read_int64(self):
        v = struct.unpack_from('>q', self.data, self.offset)[0]
        self.offset += 8
        return v

    def read_raw(self, n):
        result = self.data[self.offset:self.offset + n]
        self.offset += n
        return bytes(result)

    def read_uvarint(self):
        result = 0
        shift = 0
        while True:
            b = self.data[self.offset]
            self.offset += 1
            result |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        return result

    def read_varint(self):
        zigzag = self.read_uvarint()
        if zigzag & 1:
            return -(zigzag >> 1) - 1
        return zigzag >> 1

    def read_compact_string(self):
        length = self.read_uvarint() - 1
        if length < 0:
            return None
        return self.read_raw(length).decode('utf-8')

    def read_compact_array_int32(self):
        count = self.read_uvarint() - 1
        if count < 0:
            return None
        return [self.read_int32() for _ in range(count)]

    def read_uuid(self):
        return self.read_raw(16)

    def remaining(self):
        return len(self.data) - self.offset


# === Parsers ===

def parse_record_batches(filepath):
    """Parse all RecordBatches from a Kafka log file."""
    with open(filepath, 'rb') as f:
        data = f.read()
    batches = []
    offset = 0
    while offset < len(data):
        if offset + 21 > len(data):
            break
        batch = {}
        batch['file_offset'] = offset
        batch['base_offset'] = struct.unpack_from('>q', data, offset)[0]
        batch['batch_length'] = struct.unpack_from('>i', data, offset + 8)[0]
        batch['partition_leader_epoch'] = struct.unpack_from('>i', data, offset + 12)[0]
        batch['magic'] = struct.unpack_from('>b', data, offset + 16)[0]
        batch['crc'] = struct.unpack_from('>I', data, offset + 17)[0]

        props_length = batch['batch_length'] - 9
        props_start = offset + 21
        batch['properties_bytes'] = data[props_start:props_start + props_length]

        dec = Decoder(batch['properties_bytes'])
        batch['attributes'] = dec.read_int16()
        batch['last_offset_delta'] = dec.read_int32()
        batch['first_timestamp'] = dec.read_int64()
        batch['max_timestamp'] = dec.read_int64()
        batch['producer_id'] = dec.read_int64()
        batch['producer_epoch'] = dec.read_int16()
        batch['base_sequence'] = dec.read_int32()
        batch['record_count'] = dec.read_int32()

        records = []
        for _ in range(batch['record_count']):
            rec = {}
            rec['size'] = dec.read_varint()
            rec['attributes'] = dec.read_int8()
            rec['timestamp_delta'] = dec.read_varint()
            rec['offset_delta'] = dec.read_varint()

            key_len = dec.read_varint()
            rec['key'] = dec.read_raw(key_len) if key_len >= 0 else None

            val_len = dec.read_varint()
            rec['value'] = dec.read_raw(val_len) if val_len >= 0 else None

            headers_count = dec.read_varint()
            for _ in range(max(0, headers_count)):
                hk_len = dec.read_varint()
                if hk_len >= 0:
                    dec.read_raw(hk_len)
                hv_len = dec.read_varint()
                if hv_len >= 0:
                    dec.read_raw(hv_len)

            records.append(rec)

        batch['records'] = records
        offset += 12 + batch['batch_length']
        batches.append(batch)
    return batches


def validate_crc(batch):
    computed = crc32c(batch['properties_bytes'])
    return computed == batch['crc']


def parse_metadata_payload(value_bytes):
    """Parse a cluster metadata payload from a record value."""
    dec = Decoder(value_bytes)
    frame_version = dec.read_int8()
    type_id = dec.read_int8()
    version = dec.read_int8()

    if type_id == 12:
        name = dec.read_compact_string()
        feature_level = dec.read_int16()
        dec.read_uvarint()
        return {'type': 'FeatureLevelRecord', 'name': name, 'feature_level': feature_level}

    elif type_id == 2:
        topic_name = dec.read_compact_string()
        topic_uuid = dec.read_uuid()
        dec.read_uvarint()
        return {'type': 'TopicRecord', 'topic_name': topic_name, 'topic_uuid': topic_uuid}

    elif type_id == 3:
        partition_id = dec.read_int32()
        topic_uuid = dec.read_uuid()
        dec.read_compact_array_int32()  # replicas
        dec.read_compact_array_int32()  # isr
        dec.read_compact_array_int32()  # removing
        dec.read_compact_array_int32()  # adding
        dec.read_int32()  # leader
        dec.read_int32()  # leader_epoch
        dec.read_int32()  # partition_epoch
        dir_count = dec.read_uvarint() - 1
        dir_uuids = [dec.read_uuid() for _ in range(dir_count)]
        dec.read_uvarint()
        return {
            'type': 'PartitionRecord',
            'partition_id': partition_id,
            'topic_uuid': topic_uuid,
            'dir_uuids': dir_uuids,
        }

    return None


def extract_cluster_topology(batches):
    """Extract topics and partitions from cluster metadata batches."""
    topic_uuid_to_name = {}
    topics = {}
    partitions = {}

    for batch in batches:
        for record in batch['records']:
            if record['value'] is None:
                continue
            try:
                payload = parse_metadata_payload(record['value'])
            except Exception:
                continue
            if payload is None:
                continue
            if payload['type'] == 'TopicRecord':
                name = payload['topic_name']
                uuid = payload['topic_uuid']
                topic_uuid_to_name[uuid] = name
                topics[name] = uuid
            elif payload['type'] == 'PartitionRecord':
                uuid = payload['topic_uuid']
                name = topic_uuid_to_name.get(uuid)
                if name:
                    if name not in partitions:
                        partitions[name] = set()
                    partitions[name].add(payload['partition_id'])

    return topics, partitions


# === Fixtures ===

@pytest.fixture
def manifest():
    with open("/app/manifest.json") as f:
        return json.load(f)


# === Constants ===

KAFKA_DATA = "/app/kafka-data"
LOG_FILE = "00000000000000000000.log"
IDX_FILE = "00000000000000000000.index"
USER_PARTITIONS = [
    ("alpha-topic", 0), ("alpha-topic", 1),
    ("beta-topic", 0), ("beta-topic", 1),
]
ALL_DIRS = [
    "alpha-topic-0", "alpha-topic-1",
    "beta-topic-0", "beta-topic-1",
    "__cluster_metadata-0",
]


# === Log File Tests ===

def test_all_partition_log_files_exist():
    """All 4 partition log files must exist after repair."""
    for topic, part in USER_PARTITIONS:
        path = os.path.join(KAFKA_DATA, f"{topic}-{part}", LOG_FILE)
        assert os.path.exists(path), f"Missing log file: {topic}-{part}"
        assert os.path.getsize(path) > 0, f"Empty log file: {topic}-{part}"


def test_all_partition_log_crcs_valid():
    """Every RecordBatch in every partition log must have a valid CRC32-C."""
    for topic, part in USER_PARTITIONS:
        path = os.path.join(KAFKA_DATA, f"{topic}-{part}", LOG_FILE)
        if not os.path.exists(path):
            pytest.skip(f"Log file missing: {topic}-{part}")
        batches = parse_record_batches(path)
        assert len(batches) > 0, f"No batches in {topic}-{part}"
        for i, batch in enumerate(batches):
            assert validate_crc(batch), (
                f"CRC mismatch in {topic}-{part} batch {i}: "
                f"stored=0x{batch['crc']:08X}, "
                f"computed=0x{crc32c(batch['properties_bytes']):08X}"
            )


def test_batch_format_integrity():
    """All partition log batches must have correct magic, consistent lengths, and valid record counts."""
    for topic, part in USER_PARTITIONS:
        path = os.path.join(KAFKA_DATA, f"{topic}-{part}", LOG_FILE)
        if not os.path.exists(path):
            pytest.skip(f"Log file missing: {topic}-{part}")
        with open(path, 'rb') as f:
            raw = f.read()
        batches = parse_record_batches(path)
        assert len(batches) > 0, f"No batches in {topic}-{part}"
        for i, batch in enumerate(batches):
            assert batch['magic'] == 2, (
                f"Batch {i} in {topic}-{part} has magic={batch['magic']}, expected 2"
            )
            assert batch['record_count'] > 0, (
                f"Batch {i} in {topic}-{part} has record_count=0"
            )
            expected_end = batch['file_offset'] + 12 + batch['batch_length']
            assert expected_end <= len(raw), (
                f"Batch {i} in {topic}-{part} extends past end of file: "
                f"batch ends at {expected_end}, file is {len(raw)} bytes"
            )
            assert len(batch['properties_bytes']) == batch['batch_length'] - 9, (
                f"Batch {i} in {topic}-{part}: properties length mismatch"
            )


def test_record_values_match_manifest(manifest):
    """Decoded record values must match the manifest for all partitions."""
    for topic, part in USER_PARTITIONS:
        path = os.path.join(KAFKA_DATA, f"{topic}-{part}", LOG_FILE)
        if not os.path.exists(path):
            pytest.skip(f"Log file missing: {topic}-{part}")

        batches = parse_record_batches(path)
        actual_values = []
        for batch in batches:
            for rec in batch['records']:
                if rec['value'] is not None:
                    actual_values.append(rec['value'].decode('utf-8'))
                else:
                    actual_values.append(None)

        expected = manifest["topics"][topic]["partitions"][str(part)]["records"]
        expected_values = [r["value"] for r in expected]

        assert actual_values == expected_values, (
            f"Value mismatch in {topic}-{part}: "
            f"expected {expected_values}, got {actual_values}"
        )


def test_cluster_metadata_valid():
    """Cluster metadata must have valid CRCs and contain all topics/partitions."""
    cm_path = os.path.join(KAFKA_DATA, "__cluster_metadata-0", LOG_FILE)
    assert os.path.exists(cm_path), "Cluster metadata log missing"

    batches = parse_record_batches(cm_path)
    assert len(batches) > 0, "No batches in cluster metadata"

    for i, batch in enumerate(batches):
        assert validate_crc(batch), (
            f"CRC mismatch in cluster metadata batch {i}: "
            f"stored=0x{batch['crc']:08X}, "
            f"computed=0x{crc32c(batch['properties_bytes']):08X}"
        )

    topics, partitions = extract_cluster_topology(batches)

    assert "alpha-topic" in topics, "TopicRecord for alpha-topic not found"
    assert topics["alpha-topic"].hex() == "0102030405060708090a0b0c0d0e0f10", \
        f"Wrong UUID for alpha-topic: {topics['alpha-topic'].hex()}"

    assert "beta-topic" in topics, "TopicRecord for beta-topic not found"
    assert topics["beta-topic"].hex() == "1112131415161718191a1b1c1d1e1f20", \
        f"Wrong UUID for beta-topic: {topics['beta-topic'].hex()}"

    assert "alpha-topic" in partitions, "No PartitionRecords for alpha-topic"
    assert partitions["alpha-topic"] == {0, 1}, \
        f"alpha-topic partitions: expected {{0, 1}}, got {partitions['alpha-topic']}"

    assert "beta-topic" in partitions, "No PartitionRecords for beta-topic"
    assert partitions["beta-topic"] == {0, 1}, \
        f"beta-topic partitions: expected {{0, 1}}, got {partitions['beta-topic']}"


# === Index File Tests ===

def test_index_files_consistent():
    """Offset index files must contain valid entries mapping base offsets to batch positions."""
    for dir_name in ALL_DIRS:
        log_path = os.path.join(KAFKA_DATA, dir_name, LOG_FILE)
        idx_path = os.path.join(KAFKA_DATA, dir_name, IDX_FILE)

        if not os.path.exists(log_path):
            pytest.skip(f"Log file missing: {dir_name}")

        assert os.path.exists(idx_path), f"Missing index file: {dir_name}/{IDX_FILE}"

        batches = parse_record_batches(log_path)
        batch_map = {b['base_offset']: b['file_offset'] for b in batches}

        with open(idx_path, 'rb') as f:
            idx_data = f.read()

        assert len(idx_data) % 8 == 0, f"Index file not 8-byte aligned: {dir_name}"
        num_entries = len(idx_data) // 8
        assert num_entries > 0, f"Empty index file: {dir_name}"

        prev_offset = -1
        for i in range(num_entries):
            rel_offset, position = struct.unpack_from('>ii', idx_data, i * 8)
            assert rel_offset >= 0, (
                f"Negative offset in index entry {i} of {dir_name}: {rel_offset}"
            )
            assert rel_offset > prev_offset or i == 0, (
                f"Index entries not monotonically increasing at entry {i} in {dir_name}: "
                f"offset {rel_offset} <= previous {prev_offset}"
            )
            assert rel_offset in batch_map, (
                f"Index entry offset {rel_offset} not a batch base_offset in {dir_name}. "
                f"Valid base_offsets: {sorted(batch_map.keys())}"
            )
            assert batch_map[rel_offset] == position, (
                f"Index entry for offset {rel_offset} in {dir_name}: "
                f"position {position}, expected {batch_map[rel_offset]}"
            )
            prev_offset = rel_offset


# === Leader Epoch Checkpoint Tests ===

def test_leader_epoch_checkpoints_valid(manifest):
    """Leader-epoch-checkpoint files must exist with correct format and epochs for user partitions."""
    for topic, part in USER_PARTITIONS:
        dir_name = f"{topic}-{part}"
        cp_path = os.path.join(KAFKA_DATA, dir_name, "leader-epoch-checkpoint")

        assert os.path.exists(cp_path), f"Missing leader-epoch-checkpoint: {dir_name}"

        with open(cp_path) as f:
            lines = f.read().strip().split('\n')

        assert len(lines) >= 3, (
            f"Checkpoint too short in {dir_name}: expected at least 3 lines, got {len(lines)}"
        )
        assert lines[0] == '0', (
            f"Invalid checkpoint version in {dir_name}: expected '0', got '{lines[0]}'"
        )

        count = int(lines[1])
        assert count > 0, f"Empty checkpoint in {dir_name}"
        assert len(lines) >= 2 + count, (
            f"Checkpoint entry count mismatch in {dir_name}: "
            f"header says {count} entries, but only {len(lines) - 2} lines follow"
        )

        entries = []
        for line in lines[2:2 + count]:
            parts = line.strip().split()
            assert len(parts) == 2, (
                f"Malformed checkpoint entry in {dir_name}: '{line}'"
            )
            entries.append((int(parts[0]), int(parts[1])))

        expected_epoch = manifest['topics'][topic]['partitions'][str(part)]['leader_epoch']
        last_epoch = entries[-1][0]
        assert last_epoch == expected_epoch, (
            f"Wrong leader epoch in {dir_name}: expected {expected_epoch}, got {last_epoch}"
        )


# === Report Tests ===

def test_report_corruptions():
    """report.json must list all 6 corruption entries with correct types."""
    report_path = "/app/report.json"
    assert os.path.exists(report_path), "report.json not found"

    with open(report_path) as f:
        report = json.load(f)

    assert "corruptions" in report, "report.json missing 'corruptions' field"
    corruptions = report["corruptions"]

    corruption_map = {}
    for c in corruptions:
        assert "file" in c, f"Corruption entry missing 'file': {c}"
        assert "type" in c, f"Corruption entry missing 'type': {c}"
        fp = c["file"].replace("/app/kafka-data/", "").strip("/")
        corruption_map[fp] = c["type"]

    expected = {
        "alpha-topic-0/00000000000000000000.index": "stale_index",
        "alpha-topic-1/00000000000000000000.log": "invalid_crc",
        "alpha-topic-1/leader-epoch-checkpoint": "invalid_checkpoint",
        "beta-topic-0/00000000000000000000.log": "corrupted_data",
        "beta-topic-1/00000000000000000000.log": "missing_file",
        "__cluster_metadata-0/00000000000000000000.log": "missing_partition_record",
    }

    for file_path, expected_type in expected.items():
        assert file_path in corruption_map, \
            f"Missing corruption entry for {file_path}. Found: {list(corruption_map.keys())}"
        assert corruption_map[file_path] == expected_type, \
            f"Wrong type for {file_path}: expected '{expected_type}', got '{corruption_map[file_path]}'"


def test_report_topology():
    """report.json topology must reflect repaired cluster metadata."""
    report_path = "/app/report.json"
    assert os.path.exists(report_path), "report.json not found"

    with open(report_path) as f:
        report = json.load(f)

    assert "topology" in report, "report.json missing 'topology' field"
    topo = report["topology"]

    assert "alpha-topic" in topo, "topology missing alpha-topic"
    assert topo["alpha-topic"]["uuid_hex"] == "0102030405060708090a0b0c0d0e0f10"
    assert sorted(topo["alpha-topic"]["partitions"]) == [0, 1]

    assert "beta-topic" in topo, "topology missing beta-topic"
    assert topo["beta-topic"]["uuid_hex"] == "1112131415161718191a1b1c1d1e1f20"
    assert sorted(topo["beta-topic"]["partitions"]) == [0, 1]
