#!/usr/bin/env python3
"""Tests for Kafka broker log forensics task."""

import struct
import os
import json
import gzip
import pytest


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


# ===== Varint Decoding =====

def decode_uvarint(data, pos):
    result = 0
    shift = 0
    while True:
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            break
        shift += 7
    return result, pos

def decode_svarint(data, pos):
    zigzag, pos = decode_uvarint(data, pos)
    val = (zigzag >> 1) ^ -(zigzag & 1)
    return val, pos


# ===== RecordBatch Parsing =====

ALL_PARTITIONS = [
    "orders-0", "orders-1", "users-0",
    "events-0", "events-1", "events-2",
    "trades-0",
]

COMPRESSED_PARTITIONS = {"trades-0"}

REPAIRED_DIR = "/app/repaired"

def log_path(name):
    return f"{REPAIRED_DIR}/{name}/00000000000000000000.log"

def parse_batches(filepath):
    """Parse all complete RecordBatches from a binary log file.
    Handles both compressed and uncompressed batches."""
    with open(filepath, 'rb') as f:
        data = f.read()

    batches = []
    pos = 0
    while pos < len(data):
        if pos + 12 > len(data):
            break
        base_offset = struct.unpack_from('>q', data, pos)[0]
        batch_length = struct.unpack_from('>i', data, pos + 8)[0]
        total_size = 8 + 4 + batch_length
        if pos + total_size > len(data):
            break

        bd = data[pos:pos + total_size]
        properties = bd[21:]
        stored_crc = struct.unpack_from('>I', bd, 17)[0]
        computed_crc = crc32c(properties)

        attributes = struct.unpack_from('>h', bd, 21)[0]
        compression_codec = attributes & 0x07  # bits 0-2

        num_records = struct.unpack_from('>i', bd, 57)[0]
        raw_records_data = bytes(bd[61:])

        # Decompress records if compression is used
        if compression_codec == 1:  # gzip
            records_data = gzip.decompress(raw_records_data)
        else:
            records_data = raw_records_data

        batches.append({
            'base_offset': base_offset,
            'batch_length': batch_length,
            'magic': bd[16],
            'stored_crc': stored_crc,
            'computed_crc': computed_crc,
            'crc_valid': stored_crc == computed_crc,
            'attributes': attributes,
            'compression_codec': compression_codec,
            'last_offset_delta': struct.unpack_from('>i', bd, 23)[0],
            'num_records': num_records,
            'records_data': records_data,  # decompressed for parsing
            'producer_id': struct.unpack_from('>q', bd, 43)[0],
            'producer_epoch': struct.unpack_from('>h', bd, 51)[0],
            'base_sequence': struct.unpack_from('>i', bd, 53)[0],
            'total_size': total_size,
        })
        pos += total_size
    return batches

def count_records(batches):
    return sum(b['num_records'] for b in batches)

def extract_records(batches):
    """Parse individual records from batches, returning key/value pairs."""
    records = []
    for batch in batches:
        data = batch['records_data']
        pos = 0
        for _ in range(batch['num_records']):
            rec_size, pos = decode_svarint(data, pos)
            rec_start = pos

            _attrs = data[pos]; pos += 1
            _ts_delta, pos = decode_svarint(data, pos)
            _off_delta, pos = decode_svarint(data, pos)

            key_len, pos = decode_svarint(data, pos)
            key = None
            if key_len >= 0:
                key = bytes(data[pos:pos + key_len])
                pos += key_len

            val_len, pos = decode_svarint(data, pos)
            value = None
            if val_len >= 0:
                value = bytes(data[pos:pos + val_len])
                pos += val_len

            hdrs_count, pos = decode_svarint(data, pos)
            for _ in range(max(0, hdrs_count)):
                hk_len, pos = decode_svarint(data, pos)
                pos += max(0, hk_len)
                hv_len, pos = decode_svarint(data, pos)
                pos += max(0, hv_len)

            records.append({'key': key, 'value': value})
    return records

def file_fully_parsed(filepath):
    """Check that the file consists of exactly N complete batches with no trailing bytes."""
    with open(filepath, 'rb') as f:
        data = f.read()
    pos = 0
    while pos < len(data):
        if pos + 12 > len(data):
            return False, f"trailing {len(data) - pos} bytes (not enough for batch header)"
        bl = struct.unpack_from('>i', data, pos + 8)[0]
        total = 8 + 4 + bl
        if pos + total > len(data):
            return False, f"truncated batch at offset {pos}: needs {total} bytes, only {len(data) - pos} remain"
        pos += total
    return (pos == len(data)), f"parsed {pos} vs file {len(data)}"


# ===== Test Class =====

class TestRepairedLogs:

    # ---- Directory / file existence ----

    def test_repaired_directory_exists(self):
        assert os.path.isdir(REPAIRED_DIR), "Repaired output directory not found"

    def test_all_partition_logs_exist(self):
        for name in ALL_PARTITIONS:
            p = log_path(name)
            assert os.path.isfile(p), f"Missing: {p}"

    # ---- Structural integrity across all partitions ----

    def test_all_batches_valid_crc(self):
        for name in ALL_PARTITIONS:
            for i, b in enumerate(parse_batches(log_path(name))):
                assert b['crc_valid'], (
                    f"{name} batch {i}: CRC mismatch "
                    f"(stored=0x{b['stored_crc']:08X}, computed=0x{b['computed_crc']:08X})"
                )

    def test_all_magic_bytes_are_2(self):
        for name in ALL_PARTITIONS:
            for i, b in enumerate(parse_batches(log_path(name))):
                assert b['magic'] == 2, f"{name} batch {i}: magic={b['magic']}, expected 2"

    def test_base_offsets_sequential(self):
        for name in ALL_PARTITIONS:
            batches = parse_batches(log_path(name))
            expected = 0
            for i, b in enumerate(batches):
                assert b['base_offset'] == expected, (
                    f"{name} batch {i}: base_offset={b['base_offset']}, expected {expected}"
                )
                expected = b['base_offset'] + b['last_offset_delta'] + 1

    def test_no_trailing_bytes(self):
        for name in ALL_PARTITIONS:
            ok, msg = file_fully_parsed(log_path(name))
            assert ok, f"{name}: {msg}"

    # ---- Compression-specific tests ----

    def test_compressed_batches_retain_codec(self):
        """Compressed batches must keep their gzip codec in attributes."""
        for name in COMPRESSED_PARTITIONS:
            batches = parse_batches(log_path(name))
            for i, b in enumerate(batches):
                assert b['compression_codec'] == 1, (
                    f"{name} batch {i}: compression_codec={b['compression_codec']}, "
                    f"expected 1 (gzip)"
                )

    def test_compressed_batches_decompress_cleanly(self):
        """Gzip-compressed records must decompress without error."""
        for name in COMPRESSED_PARTITIONS:
            fp = log_path(name)
            with open(fp, 'rb') as f:
                data = f.read()
            pos = 0
            batch_idx = 0
            while pos < len(data):
                if pos + 12 > len(data):
                    break
                bl = struct.unpack_from('>i', data, pos + 8)[0]
                total = 8 + 4 + bl
                if pos + total > len(data):
                    break
                bd = data[pos:pos + total]
                attrs = struct.unpack_from('>h', bd, 21)[0]
                if (attrs & 0x07) == 1:
                    raw = bytes(bd[61:])
                    try:
                        decompressed = gzip.decompress(raw)
                    except Exception as e:
                        pytest.fail(
                            f"{name} batch {batch_idx}: gzip decompression failed: {e}"
                        )
                    assert len(decompressed) > 0, (
                        f"{name} batch {batch_idx}: decompressed to empty"
                    )
                pos += total
                batch_idx += 1

    def test_uncompressed_batches_have_no_codec(self):
        """Uncompressed partitions must have compression_codec=0 in attributes."""
        for name in ALL_PARTITIONS:
            if name in COMPRESSED_PARTITIONS:
                continue
            batches = parse_batches(log_path(name))
            for i, b in enumerate(batches):
                assert b['compression_codec'] == 0, (
                    f"{name} batch {i}: expected uncompressed (codec=0), got {b['compression_codec']}"
                )

    # ---- Per-partition structure ----

    def test_orders_0_structure(self):
        batches = parse_batches(log_path("orders-0"))
        assert len(batches) == 2
        assert count_records(batches) == 3

    def test_orders_1_structure(self):
        batches = parse_batches(log_path("orders-1"))
        assert len(batches) == 1
        assert count_records(batches) == 2

    def test_users_0_structure(self):
        batches = parse_batches(log_path("users-0"))
        assert len(batches) == 1
        assert count_records(batches) == 2

    def test_events_0_structure(self):
        batches = parse_batches(log_path("events-0"))
        assert len(batches) == 2
        assert count_records(batches) == 5

    def test_events_0_offset_repaired(self):
        batches = parse_batches(log_path("events-0"))
        assert len(batches) >= 2
        assert batches[1]['base_offset'] == 3, (
            f"events-0 batch 1: base_offset={batches[1]['base_offset']}, expected 3"
        )

    def test_events_1_structure(self):
        batches = parse_batches(log_path("events-1"))
        assert len(batches) == 1
        assert count_records(batches) == 1

    def test_events_2_structure(self):
        batches = parse_batches(log_path("events-2"))
        assert len(batches) == 1
        assert count_records(batches) == 2

    def test_trades_0_structure(self):
        batches = parse_batches(log_path("trades-0"))
        assert len(batches) == 2
        assert count_records(batches) == 4

    def test_trades_0_producer_fields(self):
        """Compressed batches with idempotent producer must preserve producer metadata."""
        batches = parse_batches(log_path("trades-0"))
        for i, b in enumerate(batches):
            assert b['producer_id'] == 1001, (
                f"trades-0 batch {i}: producer_id={b['producer_id']}, expected 1001"
            )
            assert b['producer_epoch'] == 0, (
                f"trades-0 batch {i}: producer_epoch={b['producer_epoch']}, expected 0"
            )

    # ---- Record content verification ----

    def test_record_keys_orders_0(self):
        records = extract_records(parse_batches(log_path("orders-0")))
        keys = {r['key'] for r in records if r['key'] is not None}
        assert b"order-001" in keys
        assert b"order-002" in keys
        assert b"order-003" in keys

    def test_record_keys_orders_1(self):
        records = extract_records(parse_batches(log_path("orders-1")))
        keys = {r['key'] for r in records if r['key'] is not None}
        assert b"order-004" in keys
        assert b"order-005" in keys

    def test_record_keys_users_0(self):
        records = extract_records(parse_batches(log_path("users-0")))
        keys = {r['key'] for r in records if r['key'] is not None}
        assert b"user-001" in keys
        assert b"user-002" in keys
        # Truncated batch records must NOT be present
        assert b"user-003" not in keys
        assert b"user-004" not in keys

    def test_record_keys_events_0(self):
        records = extract_records(parse_batches(log_path("events-0")))
        keys = {r['key'] for r in records if r['key'] is not None}
        for k in [b"evt-001", b"evt-002", b"evt-003", b"evt-004", b"evt-005"]:
            assert k in keys

    def test_record_keys_trades_0(self):
        """Verify decompressed records from gzip-compressed batches have correct keys."""
        records = extract_records(parse_batches(log_path("trades-0")))
        keys = {r['key'] for r in records if r['key'] is not None}
        for k in [b"trade-001", b"trade-002", b"trade-003", b"trade-004"]:
            assert k in keys, f"Missing key {k} in trades-0 decompressed records"

    def test_record_values_trades_0(self):
        """Verify decompressed trade record values are valid JSON with expected fields."""
        records = extract_records(parse_batches(log_path("trades-0")))
        for r in records:
            if r['value'] is not None:
                data = json.loads(r['value'].decode('utf-8'))
                assert "symbol" in data, "Trade record missing 'symbol' field"
                assert "action" in data, "Trade record missing 'action' field"
                assert "qty" in data, "Trade record missing 'qty' field"

    def test_record_values_are_valid_json(self):
        records = extract_records(parse_batches(log_path("orders-0")))
        for r in records:
            if r['value'] is not None:
                data = json.loads(r['value'].decode('utf-8'))
                assert "product" in data

    # ---- Total record count ----

    def test_total_records(self):
        total = 0
        for name in ALL_PARTITIONS:
            total += count_records(parse_batches(log_path(name)))
        assert total == 19, f"Total records: {total}, expected 19"

    # ---- Manifest verification ----

    def test_manifest_exists(self):
        assert os.path.isfile(f"{REPAIRED_DIR}/manifest.json"), "manifest.json not found"

    def test_manifest_has_topics(self):
        with open(f"{REPAIRED_DIR}/manifest.json") as f:
            m = json.load(f)
        assert "topics" in m
        names = {t["name"] for t in m["topics"]}
        assert names == {"orders", "users", "events", "trades"}

    def test_manifest_partition_field_names(self):
        with open(f"{REPAIRED_DIR}/manifest.json") as f:
            m = json.load(f)
        for topic in m["topics"]:
            assert "name" in topic
            assert "uuid" in topic
            assert "partitions" in topic
            for p in topic["partitions"]:
                assert "id" in p
                assert "batches" in p
                assert "records" in p
                assert "compression" in p
                assert "corruptions" in p

    def test_manifest_partition_counts(self):
        with open(f"{REPAIRED_DIR}/manifest.json") as f:
            m = json.load(f)
        topics = {t["name"]: t for t in m["topics"]}
        assert len(topics["orders"]["partitions"]) == 2
        assert len(topics["users"]["partitions"]) == 1
        assert len(topics["events"]["partitions"]) == 3
        assert len(topics["trades"]["partitions"]) == 1

    def test_manifest_topic_uuids(self):
        with open(f"{REPAIRED_DIR}/manifest.json") as f:
            m = json.load(f)
        topics = {t["name"]: t for t in m["topics"]}
        assert topics["orders"]["uuid"] == "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"
        assert topics["users"]["uuid"] == "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e"
        assert topics["events"]["uuid"] == "c3d4e5f6-a7b8-4c9d-0e1f-2a3b4c5d6e7f"
        assert topics["trades"]["uuid"] == "e5f6a7b8-c9d0-4e1f-2a3b-4c5d6e7f8091"

    def test_manifest_record_counts(self):
        with open(f"{REPAIRED_DIR}/manifest.json") as f:
            m = json.load(f)
        topics = {t["name"]: t for t in m["topics"]}

        op = {p["id"]: p for p in topics["orders"]["partitions"]}
        assert op[0]["records"] == 3
        assert op[1]["records"] == 2

        up = {p["id"]: p for p in topics["users"]["partitions"]}
        assert up[0]["records"] == 2

        ep = {p["id"]: p for p in topics["events"]["partitions"]}
        assert ep[0]["records"] == 5
        assert ep[1]["records"] == 1
        assert ep[2]["records"] == 2

        tp = {p["id"]: p for p in topics["trades"]["partitions"]}
        assert tp[0]["records"] == 4

    def test_manifest_batch_counts(self):
        with open(f"{REPAIRED_DIR}/manifest.json") as f:
            m = json.load(f)
        topics = {t["name"]: t for t in m["topics"]}

        op = {p["id"]: p for p in topics["orders"]["partitions"]}
        assert op[0]["batches"] == 2
        assert op[1]["batches"] == 1

        up = {p["id"]: p for p in topics["users"]["partitions"]}
        assert up[0]["batches"] == 1

        ep = {p["id"]: p for p in topics["events"]["partitions"]}
        assert ep[0]["batches"] == 2
        assert ep[1]["batches"] == 1
        assert ep[2]["batches"] == 1

        tp = {p["id"]: p for p in topics["trades"]["partitions"]}
        assert tp[0]["batches"] == 2

    def test_manifest_compression_codec(self):
        with open(f"{REPAIRED_DIR}/manifest.json") as f:
            m = json.load(f)
        topics = {t["name"]: t for t in m["topics"]}

        # Uncompressed topics
        for pname in ["orders", "users", "events"]:
            for p in topics[pname]["partitions"]:
                assert p["compression"] == "none", (
                    f"{pname}-{p['id']}: expected compression='none', got '{p['compression']}'"
                )

        # Compressed topic
        tp = {p["id"]: p for p in topics["trades"]["partitions"]}
        assert tp[0]["compression"] == "gzip", (
            f"trades-0: expected compression='gzip', got '{tp[0]['compression']}'"
        )

    def test_manifest_corruptions_reported(self):
        with open(f"{REPAIRED_DIR}/manifest.json") as f:
            m = json.load(f)
        topics = {t["name"]: t for t in m["topics"]}

        op = {p["id"]: p for p in topics["orders"]["partitions"]}
        assert len(op[0]["corruptions"]) == 0, "orders-0 was valid"
        assert len(op[1]["corruptions"]) > 0, "orders-1 had CRC corruption"

        up = {p["id"]: p for p in topics["users"]["partitions"]}
        assert len(up[0]["corruptions"]) > 0, "users-0 had truncation"

        ep = {p["id"]: p for p in topics["events"]["partitions"]}
        assert len(ep[0]["corruptions"]) > 0, "events-0 had offset corruption"
        assert len(ep[1]["corruptions"]) == 0, "events-1 was valid"
        assert len(ep[2]["corruptions"]) > 0, "events-2 had magic corruption"

        tp = {p["id"]: p for p in topics["trades"]["partitions"]}
        assert len(tp[0]["corruptions"]) > 0, "trades-0 had CRC corruption on compressed batch"
