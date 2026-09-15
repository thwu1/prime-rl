#!/usr/bin/env python3
"""Kafka KRaft data directory recovery solver."""

import struct
import json
import os
import sys


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
    props.write_varint(0)  # empty headers
    props_bytes = props.bytes()
    enc = Encoder()
    enc.write_varint(len(props_bytes))
    enc.write_raw(props_bytes)
    return enc.bytes()


def encode_record_batch(base_offset, partition_leader_epoch, attributes,
                        last_offset_delta, first_timestamp, max_timestamp,
                        producer_id, producer_epoch, base_sequence,
                        encoded_records):
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
    batch_length = len(props_bytes) + 9

    enc = Encoder()
    enc.write_int64(base_offset)
    enc.write_int32(batch_length)
    enc.write_int32(partition_leader_epoch)
    enc.write_int8(2)
    enc.write_uint32(crc)
    enc.write_raw(props_bytes)
    return enc.bytes()


# === Cluster Metadata Payload Encoding ===

def encode_partition_record_payload(partition_id, topic_uuid_bytes, dir_uuids):
    enc = Encoder()
    enc.write_int32(partition_id)
    enc.write_uuid(topic_uuid_bytes)
    enc.write_compact_array_int32([1])   # replicas
    enc.write_compact_array_int32([1])   # isr
    enc.write_compact_array_int32([])    # removing
    enc.write_compact_array_int32([])    # adding
    enc.write_int32(1)                   # leader
    enc.write_int32(0)                   # leader_epoch
    enc.write_int32(0)                   # partition_epoch
    enc.write_uvarint(len(dir_uuids) + 1)
    for d in dir_uuids:
        enc.write_uuid(d)
    enc.write_uvarint(0)                 # tag buffer
    return enc.bytes()


def encode_metadata_payload(frame_version, type_id, version, data_bytes):
    enc = Encoder()
    enc.write_int8(frame_version)
    enc.write_int8(type_id)
    enc.write_int8(version)
    enc.write_raw(data_bytes)
    return enc.bytes()


# === Parsers ===

def parse_record_batches(filepath):
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
    return crc32c(batch['properties_bytes']) == batch['crc']


def parse_metadata_payload(value_bytes):
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
        dec.read_compact_array_int32()
        dec.read_compact_array_int32()
        dec.read_compact_array_int32()
        dec.read_compact_array_int32()
        dec.read_int32()
        dec.read_int32()
        dec.read_int32()
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


# === Index and Checkpoint Helpers ===

def write_index_file(filepath, entries):
    """Write offset index file. entries: list of (relative_offset, position)."""
    with open(filepath, 'wb') as f:
        for rel_offset, position in entries:
            f.write(struct.pack('>ii', rel_offset, position))


def regenerate_index(log_path, idx_path):
    """Regenerate .index from .log by scanning batch positions."""
    batches = parse_record_batches(log_path)
    entries = [(b['base_offset'], b['file_offset']) for b in batches]
    write_index_file(idx_path, entries)
    return entries


def write_leader_epoch_checkpoint(filepath, entries):
    """Write leader-epoch-checkpoint. entries: list of (epoch, start_offset)."""
    with open(filepath, 'w') as f:
        f.write("0\n")
        f.write(f"{len(entries)}\n")
        for epoch, start_offset in entries:
            f.write(f"{epoch} {start_offset}\n")


def read_leader_epoch_checkpoint(filepath):
    """Read and parse a leader-epoch-checkpoint file. Returns list of (epoch, offset)."""
    if not os.path.exists(filepath):
        return None
    with open(filepath) as f:
        lines = f.read().strip().split('\n')
    if len(lines) < 2:
        return None
    try:
        count = int(lines[1])
        entries = []
        for line in lines[2:2 + count]:
            parts = line.strip().split()
            entries.append((int(parts[0]), int(parts[1])))
        return entries
    except (ValueError, IndexError):
        return None


def validate_index(log_path, idx_path):
    """Check if index entries match actual batch positions."""
    if not os.path.exists(idx_path):
        return False
    batches = parse_record_batches(log_path)
    batch_map = {b['base_offset']: b['file_offset'] for b in batches}

    with open(idx_path, 'rb') as f:
        idx_data = f.read()

    if len(idx_data) == 0 or len(idx_data) % 8 != 0:
        return False

    num_entries = len(idx_data) // 8
    for i in range(num_entries):
        rel_offset, position = struct.unpack_from('>ii', idx_data, i * 8)
        if rel_offset not in batch_map or batch_map[rel_offset] != position:
            return False
    return True


# === Repair Functions ===

def extract_values(batches):
    values = []
    for batch in batches:
        for rec in batch['records']:
            if rec['value'] is not None:
                values.append(rec['value'].decode('utf-8'))
            else:
                values.append(None)
    return values


def values_match(batches, expected_records):
    actual = extract_values(batches)
    expected = [r['value'] for r in expected_records]
    return actual == expected


def fix_crc_inplace(filepath):
    with open(filepath, 'rb') as f:
        data = bytearray(f.read())

    offset = 0
    while offset < len(data):
        batch_length = struct.unpack_from('>i', data, offset + 8)[0]
        props_length = batch_length - 9
        props_start = offset + 21
        props_bytes = data[props_start:props_start + props_length]
        new_crc = crc32c(bytes(props_bytes))
        struct.pack_into('>I', data, offset + 17, new_crc)
        offset += 12 + batch_length

    with open(filepath, 'wb') as f:
        f.write(data)


def reconstruct_partition_log(filepath, expected_records, timestamp=1726045943832):
    records = []
    for i, rec in enumerate(expected_records):
        key = rec['key'].encode('utf-8') if rec.get('key') else None
        value = rec['value'].encode('utf-8') if rec.get('value') else None
        records.append(encode_record(0, 0, i, key, value))

    batch = encode_record_batch(
        base_offset=0,
        partition_leader_epoch=1,
        attributes=0,
        last_offset_delta=len(records) - 1,
        first_timestamp=timestamp,
        max_timestamp=timestamp,
        producer_id=-1,
        producer_epoch=-1,
        base_sequence=-1,
        encoded_records=records,
    )

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'wb') as f:
        f.write(batch)


def repair_cluster_metadata(filepath, manifest, existing_partitions):
    missing = []
    for topic_name, topic_data in manifest['topics'].items():
        uuid_bytes = bytes.fromhex(topic_data['uuid_hex'])
        for part_str in topic_data['partitions']:
            part_id = int(part_str)
            if topic_name not in existing_partitions or part_id not in existing_partitions[topic_name]:
                missing.append((topic_name, uuid_bytes, part_id))

    if not missing:
        return

    batches = parse_record_batches(filepath)
    dir_uuid = None
    for batch in batches:
        for rec in batch['records']:
            if rec['value'] is None:
                continue
            try:
                payload = parse_metadata_payload(rec['value'])
            except Exception:
                continue
            if payload and payload['type'] == 'PartitionRecord' and payload.get('dir_uuids'):
                dir_uuid = payload['dir_uuids'][0]
                break
        if dir_uuid:
            break

    if dir_uuid is None:
        dir_uuid = b'\x00' * 16

    last = batches[-1]
    next_offset = last['base_offset'] + last['record_count']

    new_records = []
    for i, (topic_name, uuid_bytes, part_id) in enumerate(missing):
        part_data = encode_partition_record_payload(part_id, uuid_bytes, [dir_uuid])
        payload_bytes = encode_metadata_payload(1, 3, 1, part_data)
        new_records.append(encode_record(0, 0, i, None, payload_bytes))

    new_batch = encode_record_batch(
        base_offset=next_offset,
        partition_leader_epoch=1,
        attributes=0,
        last_offset_delta=len(new_records) - 1,
        first_timestamp=1726045944132,
        max_timestamp=1726045944132,
        producer_id=-1,
        producer_epoch=-1,
        base_sequence=-1,
        encoded_records=new_records,
    )

    with open(filepath, 'ab') as f:
        f.write(new_batch)


# === Main ===

def main():
    manifest = json.load(open('/app/manifest.json'))
    kafka_data = '/app/kafka-data'
    cm_path = os.path.join(kafka_data, '__cluster_metadata-0', '00000000000000000000.log')

    corruptions = []

    # === Parse cluster metadata to extract topology ===
    cm_batches = parse_record_batches(cm_path)
    topic_uuid_to_name = {}
    existing_partitions = {}

    for batch in cm_batches:
        for rec in batch['records']:
            if rec['value'] is None:
                continue
            try:
                payload = parse_metadata_payload(rec['value'])
            except Exception:
                continue
            if payload is None:
                continue
            if payload['type'] == 'TopicRecord':
                topic_uuid_to_name[payload['topic_uuid']] = payload['topic_name']
            elif payload['type'] == 'PartitionRecord':
                name = topic_uuid_to_name.get(payload['topic_uuid'])
                if name:
                    existing_partitions.setdefault(name, set()).add(payload['partition_id'])

    # Check for missing partition records
    for topic_name, topic_data in manifest['topics'].items():
        for part_str in topic_data['partitions']:
            part_id = int(part_str)
            if topic_name not in existing_partitions or part_id not in existing_partitions[topic_name]:
                corruptions.append({
                    'file': '__cluster_metadata-0/00000000000000000000.log',
                    'type': 'missing_partition_record',
                    'details': f'PartitionRecord for {topic_name} partition {part_id} is missing'
                })

    # === Check partition log files ===
    for topic_name, topic_data in manifest['topics'].items():
        for part_str, part_data in topic_data['partitions'].items():
            dir_name = f'{topic_name}-{part_str}'
            log_path = os.path.join(kafka_data, dir_name, '00000000000000000000.log')
            idx_path = os.path.join(kafka_data, dir_name, '00000000000000000000.index')
            cp_path = os.path.join(kafka_data, dir_name, 'leader-epoch-checkpoint')

            if not os.path.exists(log_path):
                corruptions.append({
                    'file': f'{dir_name}/00000000000000000000.log',
                    'type': 'missing_file',
                    'details': f'Log file missing for {topic_name} partition {part_str}'
                })
                print(f'Reconstructing {log_path}')
                reconstruct_partition_log(log_path, part_data['records'])
                regenerate_index(log_path, idx_path)
                expected_epoch = part_data.get('leader_epoch', 1)
                write_leader_epoch_checkpoint(cp_path, [(expected_epoch, 0)])
                continue

            batches = parse_record_batches(log_path)
            crc_ok = all(validate_crc(b) for b in batches)
            vals_ok = values_match(batches, part_data['records'])

            if not crc_ok and vals_ok:
                corruptions.append({
                    'file': f'{dir_name}/00000000000000000000.log',
                    'type': 'invalid_crc',
                    'details': f'CRC field incorrect but data intact in {topic_name} partition {part_str}'
                })
                print(f'Fixing CRC in {log_path}')
                fix_crc_inplace(log_path)

            elif not crc_ok and not vals_ok:
                corruptions.append({
                    'file': f'{dir_name}/00000000000000000000.log',
                    'type': 'corrupted_data',
                    'details': f'Record data corrupted in {topic_name} partition {part_str}'
                })
                print(f'Reconstructing {log_path}')
                reconstruct_partition_log(log_path, part_data['records'])

            elif crc_ok and not vals_ok:
                corruptions.append({
                    'file': f'{dir_name}/00000000000000000000.log',
                    'type': 'corrupted_data',
                    'details': f'Record data mismatch in {topic_name} partition {part_str}'
                })
                print(f'Reconstructing {log_path}')
                reconstruct_partition_log(log_path, part_data['records'])

            else:
                print(f'{dir_name}: log OK')

            # === Check and repair index ===
            if not validate_index(log_path, idx_path):
                corruptions.append({
                    'file': f'{dir_name}/00000000000000000000.index',
                    'type': 'stale_index',
                    'details': f'Offset index inconsistent with log in {topic_name} partition {part_str}'
                })
                print(f'Regenerating index for {dir_name}')
                regenerate_index(log_path, idx_path)
            else:
                print(f'{dir_name}: index OK')

            # === Check and repair leader-epoch-checkpoint ===
            expected_epoch = part_data.get('leader_epoch', 1)
            cp_entries = read_leader_epoch_checkpoint(cp_path)
            if cp_entries is None or cp_entries[-1][0] != expected_epoch:
                corruptions.append({
                    'file': f'{dir_name}/leader-epoch-checkpoint',
                    'type': 'invalid_checkpoint',
                    'details': f'Leader epoch checkpoint has wrong epoch in {topic_name} partition {part_str}'
                })
                print(f'Fixing checkpoint for {dir_name}')
                write_leader_epoch_checkpoint(cp_path, [(expected_epoch, 0)])
            else:
                print(f'{dir_name}: checkpoint OK')

    # === Repair cluster metadata ===
    repair_cluster_metadata(cm_path, manifest, existing_partitions)

    # === Regenerate cluster metadata index ===
    cm_idx_path = os.path.join(kafka_data, '__cluster_metadata-0', '00000000000000000000.index')
    print('Regenerating cluster metadata index')
    regenerate_index(cm_path, cm_idx_path)

    # === Build topology from manifest ===
    topology = {}
    for topic_name, topic_data in manifest['topics'].items():
        topology[topic_name] = {
            'uuid_hex': topic_data['uuid_hex'],
            'partitions': sorted(int(p) for p in topic_data['partitions'].keys())
        }

    # === Write report ===
    report = {
        'corruptions': corruptions,
        'topology': topology,
    }
    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f'\nRepair complete. Found {len(corruptions)} corruption(s).')
    print('Report written to /app/report.json')


if __name__ == '__main__':
    main()
