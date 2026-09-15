#!/usr/bin/env python3
"""Kafka binary log forensics and repair tool — reference solution."""

import struct
import os
import json
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


# ===== Varint =====

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


# ===== Cluster Metadata Parser =====

DATA_DIR = "/app/kafka-data"
OUT_DIR = "/app/repaired"

CODEC_NAMES = {0: "none", 1: "gzip", 2: "snappy", 3: "lz4", 4: "zstd"}

def parse_compact_string(data, pos):
    raw_len, pos = decode_uvarint(data, pos)
    if raw_len == 0:
        return None, pos
    str_len = raw_len - 1
    s = data[pos:pos + str_len].decode('utf-8')
    return s, pos + str_len

def parse_raw_batches(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    batches = []
    pos = 0
    while pos < len(data):
        if pos + 12 > len(data):
            break
        bl = struct.unpack_from('>i', data, pos + 8)[0]
        total = 8 + 4 + bl
        if pos + total > len(data):
            break
        batches.append(data[pos:pos + total])
        pos += total
    return batches

def get_records_data(batch_data):
    """Get decompressed records data from a batch, handling compression."""
    attributes = struct.unpack_from('>h', batch_data, 21)[0]
    codec = attributes & 0x07
    raw = bytes(batch_data[61:])
    if codec == 1:  # gzip
        return gzip.decompress(raw)
    return raw

def parse_records(batch_data):
    num = struct.unpack_from('>i', batch_data, 57)[0]
    rdata = get_records_data(batch_data)
    pos = 0
    records = []
    for _ in range(num):
        rec_size, pos = decode_svarint(rdata, pos)
        rec_start = pos
        _attr = rdata[pos]; pos += 1
        _ts, pos = decode_svarint(rdata, pos)
        _od, pos = decode_svarint(rdata, pos)
        kl, pos = decode_svarint(rdata, pos)
        key = None
        if kl >= 0:
            key = bytes(rdata[pos:pos + kl])
            pos += kl
        vl, pos = decode_svarint(rdata, pos)
        val = None
        if vl >= 0:
            val = bytes(rdata[pos:pos + vl])
            pos += vl
        hc, pos = decode_svarint(rdata, pos)
        for _ in range(max(0, hc)):
            hkl, pos = decode_svarint(rdata, pos)
            pos += max(0, hkl)
            hvl, pos = decode_svarint(rdata, pos)
            pos += max(0, hvl)
        records.append({'key': key, 'value': val})
    return records

def parse_cluster_metadata():
    meta_path = os.path.join(DATA_DIR, "__cluster_metadata-0", "00000000000000000000.log")
    batches = parse_raw_batches(meta_path)
    topics = {}  # uuid_str -> {name, uuid, partitions: []}
    for bd in batches:
        for rec in parse_records(bd):
            v = rec['value']
            if v is None or len(v) < 3:
                continue
            fv, rtype, ver = v[0], v[1], v[2]
            payload = v[3:]
            if rtype == 2:  # TopicRecord
                name, p = parse_compact_string(payload, 0)
                uuid_bytes = payload[p:p + 16]
                uid = str(uuid_mod.UUID(bytes=bytes(uuid_bytes)))
                topics[uid] = {'name': name, 'uuid': uid, 'partitions': []}
            elif rtype == 3:  # PartitionRecord
                pid = struct.unpack_from('>i', payload, 0)[0]
                uuid_bytes = payload[4:20]
                uid = str(uuid_mod.UUID(bytes=bytes(uuid_bytes)))
                if uid in topics:
                    topics[uid]['partitions'].append(pid)
    result = sorted(topics.values(), key=lambda t: t['name'])
    for t in result:
        t['partitions'].sort()
    return result


# ===== Partition Log Repair =====

def repair_partition_log(src_path, dst_path):
    with open(src_path, 'rb') as f:
        data = f.read()

    repaired = []
    corruptions = []
    expected_bo = 0
    total_records = 0
    observed_codec = 0  # track compression codec
    pos = 0

    while pos < len(data):
        if pos + 12 > len(data):
            corruptions.append("truncated_batch")
            break
        base_offset = struct.unpack_from('>q', data, pos)[0]
        bl = struct.unpack_from('>i', data, pos + 8)[0]
        total = 8 + 4 + bl
        if pos + total > len(data):
            corruptions.append("truncated_batch")
            break

        bd = bytearray(data[pos:pos + total])

        # Read attributes to detect compression
        attributes = struct.unpack_from('>h', bd, 21)[0]
        codec = attributes & 0x07
        if codec != 0:
            observed_codec = codec

        # Fix BaseOffset
        if base_offset != expected_bo:
            corruptions.append("invalid_base_offset")
            struct.pack_into('>q', bd, 0, expected_bo)

        # Fix Magic
        if bd[16] != 2:
            corruptions.append("invalid_magic")
            bd[16] = 2

        # Fix CRC — CRC covers bytes 21 onward (including compressed records)
        stored = struct.unpack_from('>I', bd, 17)[0]
        props = bytes(bd[21:])
        computed = crc32c(props)
        if stored != computed:
            corruptions.append("invalid_crc")
            struct.pack_into('>I', bd, 17, computed)

        lod = struct.unpack_from('>i', bd, 23)[0]
        nr = struct.unpack_from('>i', bd, 57)[0]
        cur_bo = struct.unpack_from('>q', bd, 0)[0]
        expected_bo = cur_bo + lod + 1
        total_records += nr
        repaired.append(bytes(bd))
        pos += total

    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    with open(dst_path, 'wb') as f:
        for b in repaired:
            f.write(b)

    return {
        'batches': len(repaired),
        'records': total_records,
        'compression': CODEC_NAMES.get(observed_codec, "none"),
        'corruptions': corruptions,
    }


# ===== Main =====

def main():
    # First, run kafka-dump-log.sh for forensic analysis on each partition
    import subprocess
    log_dirs = []
    for entry in sorted(os.listdir(DATA_DIR)):
        log_file = os.path.join(DATA_DIR, entry, "00000000000000000000.log")
        if os.path.isfile(log_file):
            log_dirs.append((entry, log_file))

    print("=== Kafka Log Forensic Analysis ===")
    for name, path in log_dirs:
        print(f"\n--- {name} ---")
        try:
            result = subprocess.run(
                ["kafka-dump-log.sh", "--files", path, "--print-data-log"],
                capture_output=True, text=True, timeout=30
            )
            if result.stdout:
                # Print first few lines of output for diagnosis
                lines = result.stdout.strip().split('\n')
                for line in lines[:10]:
                    print(f"  {line}")
            if result.stderr:
                for line in result.stderr.strip().split('\n')[:5]:
                    print(f"  [ERR] {line}")
        except Exception as e:
            print(f"  kafka-dump-log.sh failed: {e}")

    # Parse cluster metadata
    topology = parse_cluster_metadata()
    manifest_topics = []

    for topic in topology:
        entry = {'name': topic['name'], 'uuid': topic['uuid'], 'partitions': []}
        for pid in topic['partitions']:
            src = os.path.join(DATA_DIR, f"{topic['name']}-{pid}", "00000000000000000000.log")
            dst = os.path.join(OUT_DIR, f"{topic['name']}-{pid}", "00000000000000000000.log")
            result = repair_partition_log(src, dst)
            entry['partitions'].append({
                'id': pid,
                'batches': result['batches'],
                'records': result['records'],
                'compression': result['compression'],
                'corruptions': result['corruptions'],
            })
        manifest_topics.append(entry)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "manifest.json"), 'w') as f:
        json.dump({'topics': manifest_topics}, f, indent=2)

    print("\nRepair complete. Manifest written to /app/repaired/manifest.json")

if __name__ == "__main__":
    main()
