#!/usr/bin/env python3
"""
Minimal Kafka broker serving records from on-disk partition log segments.
Handles ApiVersions (v0-v3), Metadata (v0-v1), and Fetch (v0-v4).
"""

import socket
import struct
import os
import threading
import sys


# ============================================================================
# Unsigned varint codec (for flexible-version compact arrays/strings)
# ============================================================================

def encode_unsigned_varint(value):
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


# ============================================================================
# Wire protocol helpers
# ============================================================================

def encode_string(s):
    """Encode a non-nullable STRING: int16 length + UTF-8 bytes."""
    encoded = s.encode('utf-8')
    return struct.pack('>h', len(encoded)) + encoded


def decode_string(data, offset):
    """Decode a STRING. Returns (string_or_None, new_offset)."""
    if offset + 2 > len(data):
        return None, offset
    length = struct.unpack_from('>h', data, offset)[0]
    offset += 2
    if length < 0:
        return None, offset
    s = data[offset:offset + length].decode('utf-8', errors='replace')
    return s, offset + length


def encode_response_v0(correlation_id, body):
    """Wrap body with response header v0 (size + correlation_id)."""
    payload = struct.pack('>i', correlation_id) + body
    return struct.pack('>i', len(payload)) + payload


# ============================================================================
# Partition data loading
# ============================================================================

def get_high_watermark(log_data):
    """Calculate high watermark (last record offset + 1) from raw log bytes."""
    offset = 0
    hw = 0
    while offset + 61 <= len(log_data):
        base_offset = struct.unpack_from('>q', log_data, offset)[0]
        batch_length = struct.unpack_from('>i', log_data, offset + 8)[0]
        # last_offset_delta is at batch_start + 23
        last_offset_delta = struct.unpack_from('>i', log_data, offset + 23)[0]
        hw = base_offset + last_offset_delta + 1
        next_off = offset + 12 + batch_length
        if next_off <= offset:
            break
        offset = next_off
    return hw


def load_partitions(data_dir):
    """Load all partition log files. Returns {(topic, pid): bytes}."""
    partitions = {}
    for entry in sorted(os.listdir(data_dir)):
        entry_path = os.path.join(data_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        log_path = os.path.join(entry_path, '00000000000000000000.log')
        if not os.path.exists(log_path):
            continue
        parts = entry.rsplit('-', 1)
        if len(parts) != 2 or not parts[1].isdigit():
            continue
        topic, pid = parts[0], int(parts[1])
        with open(log_path, 'rb') as f:
            partitions[(topic, pid)] = f.read()
    return partitions


def get_topics(partitions):
    """Group partitions by topic. Returns {topic: sorted [pids]}."""
    topics = {}
    for topic, pid in partitions:
        topics.setdefault(topic, []).append(pid)
    for t in topics:
        topics[t].sort()
    return topics


# ============================================================================
# API Handlers
# ============================================================================

# APIs we support: (api_key, min_version, max_version)
SUPPORTED_APIS = [
    (1, 0, 4),    # Fetch
    (3, 0, 1),    # Metadata
    (18, 0, 3),   # ApiVersions
]


def handle_api_versions(correlation_id, api_version):
    """Handle ApiVersions request (API key 18)."""
    if api_version >= 3:
        # Flexible version response (v3+)
        # ApiVersions ALWAYS uses response header v0 (just correlation_id)
        body = bytearray()
        body += struct.pack('>h', 0)  # error_code = NO_ERROR
        # COMPACT_ARRAY: uvarint(count + 1)
        body += encode_unsigned_varint(len(SUPPORTED_APIS) + 1)
        for api_key, min_v, max_v in SUPPORTED_APIS:
            body += struct.pack('>hhh', api_key, min_v, max_v)
            body += bytes([0])  # empty tagged field buffer per entry
        body += struct.pack('>i', 0)  # throttle_time_ms
        body += bytes([0])  # empty tagged field buffer (response level)
        return encode_response_v0(correlation_id, bytes(body))
    else:
        # Non-flexible response (v0-v2)
        body = bytearray()
        body += struct.pack('>h', 0)  # error_code
        body += struct.pack('>i', len(SUPPORTED_APIS))  # ARRAY count
        for api_key, min_v, max_v in SUPPORTED_APIS:
            body += struct.pack('>hhh', api_key, min_v, max_v)
        if api_version >= 1:
            body += struct.pack('>i', 0)  # throttle_time_ms
        return encode_response_v0(correlation_id, bytes(body))


def handle_metadata(correlation_id, api_version, request_body, topics_dict):
    """Handle Metadata request (API key 3)."""
    # Parse requested topics from request body
    off = 0
    requested = None  # None = all topics
    if off + 4 <= len(request_body):
        count = struct.unpack_from('>i', request_body, off)[0]
        off += 4
        if count > 0:
            requested = []
            for _ in range(count):
                t, off = decode_string(request_body, off)
                if t is not None:
                    requested.append(t)
        elif count == -1:
            requested = None  # null array = all topics (v1)
        elif count == 0 and api_version == 0:
            requested = None  # v0: empty = all topics

    topics_to_return = requested if requested else sorted(topics_dict.keys())

    body = bytearray()

    # Brokers array: 1 broker (ourselves)
    body += struct.pack('>i', 1)   # broker count
    body += struct.pack('>i', 0)   # node_id = 0
    body += encode_string("localhost")
    body += struct.pack('>i', 9092)
    if api_version >= 1:
        body += struct.pack('>h', -1)  # rack = null (NULLABLE_STRING)

    if api_version >= 1:
        body += struct.pack('>i', 0)  # controller_id = 0

    # Topics array
    body += struct.pack('>i', len(topics_to_return))
    for topic in topics_to_return:
        body += struct.pack('>h', 0)  # error_code = NO_ERROR
        body += encode_string(topic)
        if api_version >= 1:
            body += bytes([0])  # is_internal = false (BOOLEAN)
        pids = topics_dict.get(topic, [])
        body += struct.pack('>i', len(pids))  # partitions count
        for pid in pids:
            body += struct.pack('>h', 0)   # error_code
            body += struct.pack('>i', pid) # partition_index
            body += struct.pack('>i', 0)   # leader = node 0
            # replicas: [0]
            body += struct.pack('>i', 1)
            body += struct.pack('>i', 0)
            # isr: [0]
            body += struct.pack('>i', 1)
            body += struct.pack('>i', 0)

    return encode_response_v0(correlation_id, bytes(body))


def handle_fetch(correlation_id, api_version, request_body, partitions):
    """Handle Fetch request (API key 1)."""
    off = 0
    # Parse request fields
    off += 4  # replica_id (int32)
    off += 4  # max_wait_ms (int32)
    off += 4  # min_bytes (int32)
    if api_version >= 3:
        off += 4  # max_bytes (int32, added in v3)
    if api_version >= 4:
        off += 1  # isolation_level (int8, added in v4)

    topics_count = struct.unpack_from('>i', request_body, off)[0]; off += 4

    fetch_topics = []
    for _ in range(topics_count):
        topic, off = decode_string(request_body, off)
        parts_count = struct.unpack_from('>i', request_body, off)[0]; off += 4
        parts = []
        for _ in range(parts_count):
            pid = struct.unpack_from('>i', request_body, off)[0]; off += 4
            fetch_offset = struct.unpack_from('>q', request_body, off)[0]; off += 8
            part_max_bytes = struct.unpack_from('>i', request_body, off)[0]; off += 4
            parts.append((pid, fetch_offset, part_max_bytes))
        fetch_topics.append((topic, parts))

    # Build response
    body = bytearray()
    if api_version >= 1:
        body += struct.pack('>i', 0)  # throttle_time_ms

    body += struct.pack('>i', len(fetch_topics))  # topics count
    for topic, parts in fetch_topics:
        body += encode_string(topic)
        body += struct.pack('>i', len(parts))  # partitions count
        for pid, fetch_offset, part_max_bytes in parts:
            log_data = partitions.get((topic, pid), b'')
            hw = get_high_watermark(log_data) if log_data else 0

            body += struct.pack('>i', pid)   # partition_index
            body += struct.pack('>h', 0)     # error_code
            body += struct.pack('>q', hw)    # high_watermark

            if api_version >= 4:
                body += struct.pack('>q', hw)    # last_stable_offset
                body += struct.pack('>i', 0)     # aborted_transactions count (empty)

            # RECORDS: send log data if offset is 0 and within range
            if fetch_offset == 0 and log_data:
                body += struct.pack('>i', len(log_data))
                body += log_data
            else:
                body += struct.pack('>i', 0)  # empty record set

    return encode_response_v0(correlation_id, bytes(body))


# ============================================================================
# Connection handler
# ============================================================================

def handle_connection(conn, addr, partitions, topics_dict):
    """Handle a single client TCP connection (multiple request/response cycles)."""
    try:
        buf = b''
        while True:
            # Read 4-byte message size prefix
            while len(buf) < 4:
                chunk = conn.recv(8192)
                if not chunk:
                    return
                buf += chunk

            msg_size = struct.unpack('>i', buf[:4])[0]
            buf = buf[4:]

            # Read full message
            while len(buf) < msg_size:
                chunk = conn.recv(8192)
                if not chunk:
                    return
                buf += chunk

            msg = buf[:msg_size]
            buf = buf[msg_size:]

            # Parse request header (common fields at fixed offsets)
            if len(msg) < 10:
                continue
            api_key = struct.unpack_from('>h', msg, 0)[0]
            api_version = struct.unpack_from('>h', msg, 2)[0]
            correlation_id = struct.unpack_from('>i', msg, 4)[0]

            # Client ID (STRING: int16 length + bytes)
            client_id_len = struct.unpack_from('>h', msg, 8)[0]
            header_end = 10 + (client_id_len if client_id_len >= 0 else 0)

            # For flexible-version request headers (ApiVersions v3+),
            # skip the tagged field buffer at end of header
            if api_key == 18 and api_version >= 3:
                if header_end < len(msg):
                    # Tag buffer: uvarint count of tagged fields (0 = empty)
                    # For the common case, this is a single byte 0x00
                    tag_byte = msg[header_end]
                    header_end += 1
                    # If tag_byte > 0, there are tagged fields to skip
                    # (extremely rare in practice; kcat sends 0)

            request_body = msg[header_end:] if header_end <= len(msg) else b''

            # Route to API handler
            if api_key == 18:
                response = handle_api_versions(correlation_id, api_version)
            elif api_key == 3:
                response = handle_metadata(
                    correlation_id, api_version, request_body, topics_dict)
            elif api_key == 1:
                response = handle_fetch(
                    correlation_id, api_version, request_body, partitions)
            else:
                # Unknown API: empty error response
                body = struct.pack('>h', 35)  # UNSUPPORTED_VERSION
                response = encode_response_v0(correlation_id, body)

            conn.sendall(response)

    except Exception as e:
        print(f"Connection error from {addr}: {e}", file=sys.stderr)
        sys.stderr.flush()
    finally:
        conn.close()


# ============================================================================
# Main
# ============================================================================

def main():
    data_dir = '/app/data'
    partitions = load_partitions(data_dir)
    topics_dict = get_topics(partitions)

    topic_summary = {t: len(pids) for t, pids in topics_dict.items()}
    print(f"Loaded {len(partitions)} partitions: {topic_summary}")
    sys.stdout.flush()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', 9092))
    server.listen(5)
    print("Kafka broker listening on port 9092")
    sys.stdout.flush()

    while True:
        conn, addr = server.accept()
        t = threading.Thread(
            target=handle_connection,
            args=(conn, addr, partitions, topics_dict),
            daemon=True
        )
        t.start()


if __name__ == '__main__':
    main()
