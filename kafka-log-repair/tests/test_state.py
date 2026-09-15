
import pytest
import struct
import os
import json
import socket
import time

# ============================================================================
# CRC32-C (Castagnoli) -- needed to verify repaired checksums
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
# Zigzag varint decoding -- needed to parse records for verification
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
# Expected values (hard-coded to prevent gaming)
# ============================================================================

PARTITIONS = ['orders-0', 'orders-1', 'events-0', 'events-1', 'metrics-0']

EXPECTED_STRUCTURE = {
    'orders-0': {'batches': 1, 'total_records': 3},
    'orders-1': {'batches': 1, 'total_records': 2},
    'events-0': {'batches': 2, 'total_records': 4},
    'events-1': {'batches': 1, 'total_records': 3},
    'metrics-0': {'batches': 1, 'total_records': 2},
}

EXPECTED_CORRUPTIONS = {
    ('orders-0', 0): 'invalid_crc',
    ('orders-1', 0): 'invalid_batch_length',
    ('events-0', 1): 'invalid_magic',
    ('events-1', 0): 'invalid_record_count',
    ('metrics-0', 0): 'invalid_timestamps',
}

# ============================================================================
# Helper: parse a batch header from binary data
# ============================================================================

def parse_batch_header(data, offset):
    batch_start = offset
    base_offset = struct.unpack_from('>q', data, offset)[0]; offset += 8
    batch_length = struct.unpack_from('>i', data, offset)[0]; offset += 4
    ple = struct.unpack_from('>i', data, offset)[0]; offset += 4
    magic = data[offset]; offset += 1
    stored_crc = struct.unpack_from('>I', data, offset)[0]; offset += 4
    props_start = offset
    attributes = struct.unpack_from('>h', data, offset)[0]; offset += 2
    last_offset_delta = struct.unpack_from('>i', data, offset)[0]; offset += 4
    first_ts = struct.unpack_from('>q', data, offset)[0]; offset += 8
    max_ts = struct.unpack_from('>q', data, offset)[0]; offset += 8
    producer_id = struct.unpack_from('>q', data, offset)[0]; offset += 8
    producer_epoch = struct.unpack_from('>h', data, offset)[0]; offset += 2
    base_seq = struct.unpack_from('>i', data, offset)[0]; offset += 4
    record_count = struct.unpack_from('>i', data, offset)[0]; offset += 4
    return {
        'batch_start': batch_start,
        'base_offset': base_offset,
        'batch_length': batch_length,
        'ple': ple,
        'magic': magic,
        'stored_crc': stored_crc,
        'props_start': props_start,
        'attributes': attributes,
        'last_offset_delta': last_offset_delta,
        'first_ts': first_ts,
        'max_ts': max_ts,
        'producer_id': producer_id,
        'producer_epoch': producer_epoch,
        'base_seq': base_seq,
        'record_count': record_count,
    }, offset


def parse_record(data, offset):
    size, offset = decode_varint_signed(data, offset)
    body_end = offset + size
    attrs = data[offset]; offset += 1
    ts_delta, offset = decode_varint_signed(data, offset)
    off_delta, offset = decode_varint_signed(data, offset)
    key_len, offset = decode_varint_signed(data, offset)
    key = None
    if key_len >= 0:
        key = data[offset:offset + key_len]
        offset += key_len
    val_len, offset = decode_varint_signed(data, offset)
    value = None
    if val_len >= 0:
        value = data[offset:offset + val_len]
        offset += val_len
    return key, value, body_end


def read_log(name):
    path = f'/app/data/{name}/00000000000000000000.log'
    with open(path, 'rb') as f:
        return f.read()


def is_port_open(port, host='localhost', timeout=2):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


# ============================================================================
# Kafka wire protocol helpers for broker testing
# ============================================================================

def _encode_unsigned_varint(value):
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def _recv_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed while reading")
        buf += chunk
    return buf


def _send_kafka_request(sock, api_key, api_version, correlation_id, body):
    """Send a Kafka request and read the framed response."""
    header = struct.pack('>hhih', api_key, api_version, correlation_id, 4) + b'test'
    if api_key == 18 and api_version >= 3:
        header += bytes([0])
    msg = header + body
    sock.sendall(struct.pack('>i', len(msg)) + msg)
    resp_size = struct.unpack('>i', _recv_exact(sock, 4))[0]
    return _recv_exact(sock, resp_size)


def _decode_string(data, offset):
    length = struct.unpack_from('>h', data, offset)[0]
    offset += 2
    if length < 0:
        return None, offset
    return data[offset:offset + length].decode('utf-8', errors='replace'), offset + length


def _extract_records_from_batches(rec_data):
    """Parse RecordBatch(es) and return list of record value strings."""
    values = []
    roff = 0
    while roff + 61 <= len(rec_data):
        bl = struct.unpack_from('>i', rec_data, roff + 8)[0]
        rc = struct.unpack_from('>i', rec_data, roff + 57)[0]
        rec_start = roff + 61
        for _ in range(rc):
            rsize, rec_start = decode_varint_signed(rec_data, rec_start)
            body_end = rec_start + rsize
            _attrs = rec_data[rec_start]; rec_start += 1
            _, rec_start = decode_varint_signed(rec_data, rec_start)
            _, rec_start = decode_varint_signed(rec_data, rec_start)
            key_len, rec_start = decode_varint_signed(rec_data, rec_start)
            if key_len >= 0:
                rec_start += key_len
            val_len, rec_start = decode_varint_signed(rec_data, rec_start)
            if val_len >= 0:
                values.append(rec_data[rec_start:rec_start + val_len].decode('utf-8', errors='replace'))
                rec_start += val_len
            rec_start = body_end
        roff += 12 + bl
    return values


def fetch_topic_via_wire(topic, timeout=15):
    """Connect to broker, negotiate versions, fetch all records for a topic.

    Returns (messages_list, error_string_or_None).
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(('localhost', 9092))
    except Exception as e:
        return [], f"Cannot connect to broker: {e}"

    try:
        # Step 1: ApiVersions v3
        av_body = (_encode_unsigned_varint(5) + b'test' + b'\x00'
                   + _encode_unsigned_varint(4) + b'1.0' + b'\x00'
                   + bytes([0]))
        resp = _send_kafka_request(sock, 18, 3, 1, av_body)
        error_code = struct.unpack_from('>h', resp, 4)[0]
        if error_code != 0:
            return [], f"ApiVersions error: {error_code}"

        # Determine max Fetch version from ApiVersions response
        # Parse compact array
        off = 6
        arr_len_byte = resp[off]; off += 1
        num_apis = arr_len_byte - 1
        max_fetch_version = 0
        for _ in range(num_apis):
            ak = struct.unpack_from('>h', resp, off)[0]; off += 2
            _minv = struct.unpack_from('>h', resp, off)[0]; off += 2
            maxv = struct.unpack_from('>h', resp, off)[0]; off += 2
            off += 1  # tag buffer
            if ak == 1:
                max_fetch_version = maxv

        # Step 2: Metadata v1
        meta_body = struct.pack('>ih', 1, len(topic)) + topic.encode('utf-8')
        resp = _send_kafka_request(sock, 3, 1, 2, meta_body)

        # Parse metadata to get partition list
        off = 4  # skip correlation_id
        broker_count = struct.unpack_from('>i', resp, off)[0]; off += 4
        for _ in range(broker_count):
            off += 4  # node_id
            host_len = struct.unpack_from('>h', resp, off)[0]; off += 2
            if host_len >= 0:
                off += host_len
            off += 4  # port
            rack_len = struct.unpack_from('>h', resp, off)[0]; off += 2
            if rack_len >= 0:
                off += rack_len
        off += 4  # controller_id

        topic_count = struct.unpack_from('>i', resp, off)[0]; off += 4
        partition_ids = []
        for _ in range(topic_count):
            off += 2  # error_code
            tname_len = struct.unpack_from('>h', resp, off)[0]; off += 2
            off += tname_len  # topic name
            off += 1  # is_internal
            part_count = struct.unpack_from('>i', resp, off)[0]; off += 4
            for _ in range(part_count):
                off += 2  # error_code
                pidx = struct.unpack_from('>i', resp, off)[0]; off += 4
                partition_ids.append(pidx)
                off += 4  # leader
                rep_cnt = struct.unpack_from('>i', resp, off)[0]; off += 4
                off += rep_cnt * 4
                isr_cnt = struct.unpack_from('>i', resp, off)[0]; off += 4
                off += isr_cnt * 4

        if not partition_ids:
            return [], f"No partitions found for topic '{topic}'"

        # Step 3: Fetch v4
        use_v4 = max_fetch_version >= 4
        fetch_version = 4 if use_v4 else min(max_fetch_version, 4)

        fetch_body = struct.pack('>i', -1)  # replica_id
        fetch_body += struct.pack('>i', 5000)  # max_wait_ms
        fetch_body += struct.pack('>i', 1)  # min_bytes
        if fetch_version >= 3:
            fetch_body += struct.pack('>i', 16777216)  # max_bytes
        if fetch_version >= 4:
            fetch_body += struct.pack('>b', 0)  # isolation_level
        fetch_body += struct.pack('>i', 1)  # 1 topic
        fetch_body += struct.pack('>h', len(topic)) + topic.encode('utf-8')
        fetch_body += struct.pack('>i', len(partition_ids))
        for pid in sorted(partition_ids):
            fetch_body += struct.pack('>i', pid)
            fetch_body += struct.pack('>q', 0)  # fetch_offset = 0
            fetch_body += struct.pack('>i', 16777216)  # partition_max_bytes

        resp = _send_kafka_request(sock, 1, fetch_version, 3, fetch_body)

        # Parse Fetch response
        off = 4  # skip correlation_id
        if fetch_version >= 1:
            off += 4  # throttle_time_ms

        all_values = []
        ftopic_count = struct.unpack_from('>i', resp, off)[0]; off += 4
        for _ in range(ftopic_count):
            tname_len = struct.unpack_from('>h', resp, off)[0]; off += 2
            off += tname_len
            pcount = struct.unpack_from('>i', resp, off)[0]; off += 4
            for _ in range(pcount):
                off += 4  # partition_index
                perr = struct.unpack_from('>h', resp, off)[0]; off += 2
                off += 8  # high_watermark
                if fetch_version >= 4:
                    off += 8  # last_stable_offset
                    aborted_cnt = struct.unpack_from('>i', resp, off)[0]; off += 4
                    off += aborted_cnt * 16
                rec_size = struct.unpack_from('>i', resp, off)[0]; off += 4
                if rec_size > 0:
                    rec_data = resp[off:off + rec_size]
                    off += rec_size
                    all_values.extend(_extract_records_from_batches(rec_data))
                elif rec_size == 0:
                    pass  # no records
                else:
                    off += 0  # null records (-1)

        return all_values, None

    except Exception as e:
        return [], f"Wire protocol error: {e}"
    finally:
        sock.close()


# ============================================================================
# Log Repair Tests
# ============================================================================

class TestFilesExist:
    def test_all_log_files_exist(self):
        for name in PARTITIONS:
            path = f'/app/data/{name}/00000000000000000000.log'
            assert os.path.exists(path), f"Missing log file: {path}"

    def test_report_exists(self):
        assert os.path.exists('/app/report.json'), "Missing /app/report.json"

    def test_repair_tool_exists(self):
        assert os.path.exists('/app/repair_tool.py'), "Missing /app/repair_tool.py"

    def test_broker_exists(self):
        assert os.path.exists('/app/broker.py'), "Missing /app/broker.py"


class TestCRCValidity:
    """Every RecordBatch must have a valid CRC32-C checksum after repair."""

    @pytest.mark.parametrize("name", PARTITIONS)
    def test_crc_valid(self, name):
        data = read_log(name)
        offset = 0
        batch_idx = 0
        while offset < len(data):
            hdr, rec_offset = parse_batch_header(data, offset)
            batch_end = hdr['batch_start'] + 12 + hdr['batch_length']
            assert batch_end <= len(data), (
                f"{name} batch {batch_idx}: batch extends past file end "
                f"({batch_end} > {len(data)})"
            )
            props = data[hdr['props_start']:batch_end]
            computed = crc32c(props)
            assert hdr['stored_crc'] == computed, (
                f"{name} batch {batch_idx}: CRC mismatch -- "
                f"stored=0x{hdr['stored_crc']:08X}, computed=0x{computed:08X}"
            )
            offset = batch_end
            batch_idx += 1


class TestMagicByte:
    @pytest.mark.parametrize("name", PARTITIONS)
    def test_magic_is_2(self, name):
        data = read_log(name)
        offset = 0
        batch_idx = 0
        while offset < len(data):
            hdr, _ = parse_batch_header(data, offset)
            assert hdr['magic'] == 2, (
                f"{name} batch {batch_idx}: magic={hdr['magic']}, expected 2"
            )
            offset = hdr['batch_start'] + 12 + hdr['batch_length']
            batch_idx += 1


class TestBatchLength:
    @pytest.mark.parametrize("name", PARTITIONS)
    def test_batch_length_valid(self, name):
        data = read_log(name)
        offset = 0
        while offset < len(data):
            hdr, _ = parse_batch_header(data, offset)
            batch_end = hdr['batch_start'] + 12 + hdr['batch_length']
            assert batch_end <= len(data), (
                f"{name}: BatchLength extends past file end"
            )
            offset = batch_end
        assert offset == len(data), (
            f"{name}: trailing bytes after last batch ({len(data) - offset})"
        )


class TestTimestamps:
    @pytest.mark.parametrize("name", PARTITIONS)
    def test_first_le_max(self, name):
        data = read_log(name)
        offset = 0
        batch_idx = 0
        while offset < len(data):
            hdr, _ = parse_batch_header(data, offset)
            assert hdr['first_ts'] <= hdr['max_ts'], (
                f"{name} batch {batch_idx}: FirstTimestamp ({hdr['first_ts']}) > "
                f"MaxTimestamp ({hdr['max_ts']})"
            )
            offset = hdr['batch_start'] + 12 + hdr['batch_length']
            batch_idx += 1


class TestRecordCounts:
    @pytest.mark.parametrize("name", PARTITIONS)
    def test_record_count_matches(self, name):
        expected = EXPECTED_STRUCTURE[name]
        data = read_log(name)
        offset = 0
        batch_count = 0
        total_records = 0
        while offset < len(data):
            hdr, rec_offset = parse_batch_header(data, offset)
            batch_end = hdr['batch_start'] + 12 + hdr['batch_length']
            parsed = 0
            ro = rec_offset
            for _ in range(hdr['record_count']):
                _, _, ro = parse_record(data, ro)
                parsed += 1
            assert parsed == hdr['record_count'], (
                f"{name} batch {batch_count}: could only parse {parsed} of "
                f"{hdr['record_count']} records"
            )
            assert ro <= batch_end, (
                f"{name} batch {batch_count}: records extend past batch boundary"
            )
            total_records += hdr['record_count']
            batch_count += 1
            offset = batch_end
        assert batch_count == expected['batches'], (
            f"{name}: expected {expected['batches']} batches, got {batch_count}"
        )
        assert total_records == expected['total_records'], (
            f"{name}: expected {expected['total_records']} records, got {total_records}"
        )


class TestReportStructure:
    def test_report_has_five_corruptions(self):
        with open('/app/report.json') as f:
            report = json.load(f)
        assert 'corruptions' in report
        assert len(report['corruptions']) == 5, (
            f"Expected 5 corruptions, got {len(report['corruptions'])}"
        )

    def test_corruption_types_correct(self):
        with open('/app/report.json') as f:
            report = json.load(f)
        found = {}
        for c in report['corruptions']:
            assert 'file' in c, "Corruption entry missing 'file'"
            assert 'batch_index' in c, "Corruption entry missing 'batch_index'"
            assert 'type' in c, "Corruption entry missing 'type'"
            assert 'details' in c, "Corruption entry missing 'details'"
            partition = c['file'].split('/')[0]
            found[(partition, c['batch_index'])] = c['type']
        for key, expected_type in EXPECTED_CORRUPTIONS.items():
            assert key in found, (
                f"Missing corruption entry for {key[0]} batch {key[1]}"
            )
            assert found[key] == expected_type, (
                f"{key[0]} batch {key[1]}: expected type '{expected_type}', "
                f"got '{found[key]}'"
            )


class TestRecordContent:
    """Verify specific records are readable and contain expected values."""

    def test_orders0_first_record(self):
        data = read_log('orders-0')
        _, rec_offset = parse_batch_header(data, 0)
        key, value, _ = parse_record(data, rec_offset)
        assert key == b"order-id"
        assert value == b"order-1001: laptop, qty=2"

    def test_orders0_third_record(self):
        data = read_log('orders-0')
        _, rec_offset = parse_batch_header(data, 0)
        _, _, rec_offset = parse_record(data, rec_offset)
        _, _, rec_offset = parse_record(data, rec_offset)
        key, value, _ = parse_record(data, rec_offset)
        assert key == b"order-id"
        assert value == b"order-1003: monitor, qty=1"

    def test_orders1_records(self):
        data = read_log('orders-1')
        _, rec_offset = parse_batch_header(data, 0)
        key, value, rec_offset = parse_record(data, rec_offset)
        assert key == b"order-id"
        assert value == b"order-2001: mouse, qty=10"
        key, value, _ = parse_record(data, rec_offset)
        assert key == b"order-id"
        assert value == b"order-2002: cable, qty=20"

    def test_events0_second_batch_records(self):
        data = read_log('events-0')
        hdr1, _ = parse_batch_header(data, 0)
        batch2_start = hdr1['batch_start'] + 12 + hdr1['batch_length']
        _, rec_offset = parse_batch_header(data, batch2_start)
        key, value, rec_offset = parse_record(data, rec_offset)
        assert key == b"event-type"
        assert value == b"user.logout: alice"
        key, value, _ = parse_record(data, rec_offset)
        assert key == b"event-type"
        assert value == b"user.purchase: bob"

    def test_events1_records(self):
        data = read_log('events-1')
        _, rec_offset = parse_batch_header(data, 0)
        key, value, rec_offset = parse_record(data, rec_offset)
        assert key == b"page"
        assert value == b"page.view: /home"
        key, value, rec_offset = parse_record(data, rec_offset)
        assert value == b"page.view: /products"
        key, value, _ = parse_record(data, rec_offset)
        assert value == b"page.view: /checkout"

    def test_metrics0_records(self):
        data = read_log('metrics-0')
        _, rec_offset = parse_batch_header(data, 0)
        key, value, rec_offset = parse_record(data, rec_offset)
        assert key == b"metric"
        assert value == b"cpu.usage: 78.5"
        key, value, _ = parse_record(data, rec_offset)
        assert key == b"metric"
        assert value == b"memory.usage: 62.3"


# ============================================================================
# Broker Wire Protocol Tests (Python Kafka client)
# ============================================================================

class TestBrokerAvailable:
    """Verify broker is listening on port 9092."""

    def test_port_9092_open(self):
        assert is_port_open(9092), (
            "Broker not listening on port 9092. "
            "Ensure /app/broker.py is running."
        )


class TestBrokerOrders:
    """Verify broker serves all order messages via Kafka wire protocol."""

    def test_orders_all_messages(self):
        messages, err = fetch_topic_via_wire('orders')
        assert err is None, f"Failed to fetch orders: {err}"
        expected = [
            'order-1001: laptop, qty=2',
            'order-1002: keyboard, qty=5',
            'order-1003: monitor, qty=1',
            'order-2001: mouse, qty=10',
            'order-2002: cable, qty=20',
        ]
        for msg in expected:
            assert msg in messages, (
                f"Missing message in orders: '{msg}'. Got: {messages}"
            )
        assert len(messages) == 5, (
            f"Expected 5 order messages, got {len(messages)}: {messages}"
        )


class TestBrokerEvents:
    """Verify broker serves all event messages via Kafka wire protocol."""

    def test_events_all_messages(self):
        messages, err = fetch_topic_via_wire('events')
        assert err is None, f"Failed to fetch events: {err}"
        expected = [
            'user.login: alice',
            'user.login: bob',
            'user.logout: alice',
            'user.purchase: bob',
            'page.view: /home',
            'page.view: /products',
            'page.view: /checkout',
        ]
        for msg in expected:
            assert msg in messages, (
                f"Missing message in events: '{msg}'. Got: {messages}"
            )
        assert len(messages) == 7, (
            f"Expected 7 event messages, got {len(messages)}: {messages}"
        )


class TestBrokerMetrics:
    """Verify broker serves all metric messages via Kafka wire protocol."""

    def test_metrics_all_messages(self):
        messages, err = fetch_topic_via_wire('metrics')
        assert err is None, f"Failed to fetch metrics: {err}"
        expected = [
            'cpu.usage: 78.5',
            'memory.usage: 62.3',
        ]
        for msg in expected:
            assert msg in messages, (
                f"Missing message in metrics: '{msg}'. Got: {messages}"
            )
        assert len(messages) == 2, (
            f"Expected 2 metric messages, got {len(messages)}: {messages}"
        )
