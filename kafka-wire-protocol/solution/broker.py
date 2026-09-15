#!/usr/bin/env python3
"""Kafka wire protocol broker — handles ApiVersions, Metadata, DescribeTopicPartitions, Fetch.

"""

import os
import socket
import struct
import threading

KRAFT_LOG_DIR = "/data/kraft-combined-logs"
METADATA_LOG = os.path.join(KRAFT_LOG_DIR, "__cluster_metadata-0",
                            "00000000000000000000.log")

# ─── Binary reader ───────────────────────────────────────────────────────

class BinaryReader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read(self, n):
        r = self.data[self.pos:self.pos + n]
        self.pos += n
        return r

    def read_int8(self):
        return struct.unpack('>b', self.read(1))[0]

    def read_int16(self):
        return struct.unpack('>h', self.read(2))[0]

    def read_int32(self):
        return struct.unpack('>i', self.read(4))[0]

    def read_uint32(self):
        return struct.unpack('>I', self.read(4))[0]

    def read_int64(self):
        return struct.unpack('>q', self.read(8))[0]

    def read_uvarint(self):
        result = 0
        shift = 0
        while True:
            b = self.data[self.pos]
            self.pos += 1
            result |= (b & 0x7f) << shift
            if not (b & 0x80):
                break
            shift += 7
        return result

    def read_varint(self):
        uv = self.read_uvarint()
        return (uv >> 1) ^ -(uv & 1)

    def read_uuid(self):
        return self.read(16)

    def read_compact_string(self):
        length = self.read_uvarint() - 1
        if length < 0:
            return None
        return self.read(length).decode('utf-8')

    def read_nullable_string(self):
        length = self.read_int16()
        if length < 0:
            return None
        return self.read(length).decode('utf-8')

    def read_compact_array_int32(self):
        count = self.read_uvarint() - 1
        return [self.read_int32() for _ in range(count)]

    def remaining(self):
        return len(self.data) - self.pos


# ─── Binary writer ───────────────────────────────────────────────────────

class BinaryWriter:
    def __init__(self):
        self.buf = bytearray()

    def write_int8(self, v):
        self.buf += struct.pack('>b', v)

    def write_int16(self, v):
        self.buf += struct.pack('>h', v)

    def write_int32(self, v):
        self.buf += struct.pack('>i', v)

    def write_int64(self, v):
        self.buf += struct.pack('>q', v)

    def write_uvarint(self, v):
        while v > 0x7f:
            self.buf.append((v & 0x7f) | 0x80)
            v >>= 7
        self.buf.append(v & 0x7f)

    def write_raw(self, data):
        self.buf += data

    def write_compact_string(self, s):
        b = s.encode('utf-8')
        self.write_uvarint(len(b) + 1)
        self.buf += b

    def write_compact_array_int32(self, arr):
        self.write_uvarint(len(arr) + 1)
        for v in arr:
            self.write_int32(v)

    def write_compact_nullable_bytes(self, data):
        if data is None:
            self.write_uvarint(0)
        else:
            self.write_uvarint(len(data) + 1)
            self.buf += data

    # Old-style (non-compact) encoding for Metadata API
    def write_old_string(self, s):
        b = s.encode('utf-8')
        self.write_int16(len(b))
        self.buf += b

    def write_old_nullable_string(self, s):
        if s is None:
            self.write_int16(-1)
        else:
            self.write_old_string(s)

    def write_old_array_int32(self, arr):
        self.write_int32(len(arr))
        for v in arr:
            self.write_int32(v)

    def bytes(self):
        return bytes(self.buf)


# ─── Flexible versioning ────────────────────────────────────────────────

def is_flexible_version(api_key, api_version):
    """Return True if (api_key, api_version) uses flexible versioning (header v2)."""
    if api_key == 18:  # ApiVersions
        return api_version >= 3
    elif api_key == 3:  # Metadata
        return api_version >= 9
    elif api_key == 1:  # Fetch
        return api_version >= 12
    elif api_key == 75:  # DescribeTopicPartitions
        return True
    return False


# ─── Cluster metadata parser ────────────────────────────────────────────

def parse_cluster_metadata():
    """Parse cluster metadata log and return (topics_by_name, topics_by_uuid)."""
    with open(METADATA_LOG, 'rb') as f:
        data = f.read()

    topics_by_name = {}
    topics_by_uuid = {}

    r = BinaryReader(data)
    while r.remaining() > 0:
        r.read_int64()   # baseOffset
        r.read_int32()   # batchLength
        r.read_int32()   # partitionLeaderEpoch
        r.read_int8()    # magic
        r.read_uint32()  # CRC
        r.read_int16()   # attributes
        r.read_int32()   # lastOffsetDelta
        r.read_int64()   # firstTimestamp
        r.read_int64()   # maxTimestamp
        r.read_int64()   # producerId
        r.read_int16()   # producerEpoch
        r.read_int32()   # baseSequence
        record_count = r.read_int32()

        for _ in range(record_count):
            rec_size = r.read_varint()
            rec_data = r.read(rec_size)
            rr = BinaryReader(rec_data)
            rr.read_int8()    # attributes
            rr.read_varint()  # timestampDelta
            rr.read_varint()  # offsetDelta
            key_len = rr.read_varint()
            if key_len >= 0:
                rr.read(key_len)
            val_len = rr.read_varint()
            if val_len < 0:
                continue
            value_data = rr.read(val_len)
            _parse_payload(value_data, topics_by_name, topics_by_uuid)

    return topics_by_name, topics_by_uuid


def _parse_payload(data, topics_by_name, topics_by_uuid):
    pr = BinaryReader(data)
    pr.read_int8()          # frameVersion
    type_id = pr.read_int8()
    pr.read_int8()          # version

    if type_id == 2:  # TopicRecord
        name = pr.read_compact_string()
        uuid_bytes = pr.read_uuid()
        topics_by_name[name] = {"uuid": uuid_bytes, "partitions": {}}
        topics_by_uuid[uuid_bytes] = name

    elif type_id == 3:  # PartitionRecord
        partition_id = pr.read_int32()
        topic_uuid = pr.read_uuid()
        replicas = pr.read_compact_array_int32()
        isr = pr.read_compact_array_int32()
        pr.read_compact_array_int32()  # removingReplicas
        pr.read_compact_array_int32()  # addingReplicas
        leader = pr.read_int32()
        leader_epoch = pr.read_int32()
        pr.read_int32()                # partitionEpoch
        dir_count = pr.read_uvarint() - 1
        for _ in range(dir_count):
            pr.read_uuid()
        pr.read_uvarint()  # tag buffer

        topic_name = topics_by_uuid.get(topic_uuid)
        if topic_name and topic_name in topics_by_name:
            topics_by_name[topic_name]["partitions"][partition_id] = {
                "leader": leader,
                "leader_epoch": leader_epoch,
                "replicas": replicas,
                "isr": isr,
            }


# ─── Request parsing helpers ────────────────────────────────────────────

def parse_request_header(r):
    """Parse request header, detecting v1 vs v2 based on api_key/version."""
    api_key = r.read_int16()
    api_version = r.read_int16()
    correlation_id = r.read_int32()
    r.read_nullable_string()  # client_id
    if is_flexible_version(api_key, api_version):
        r.read_uvarint()      # tag buffer (header v2 only)
    return api_key, api_version, correlation_id


def parse_dtp_body(r):
    count = r.read_uvarint() - 1
    names = []
    for _ in range(count):
        names.append(r.read_compact_string())
        r.read_uvarint()  # tag buffer
    return names


def parse_fetch_body(r):
    r.read_int32()   # maxWaitMs
    r.read_int32()   # minBytes
    r.read_int32()   # maxBytes
    r.read_int8()    # isolationLevel
    r.read_int32()   # sessionId
    r.read_int32()   # sessionEpoch
    topic_count = r.read_uvarint() - 1
    topics = []
    for _ in range(topic_count):
        uuid_bytes = r.read_uuid()
        part_count = r.read_uvarint() - 1
        partitions = []
        for _ in range(part_count):
            pid = r.read_int32()
            r.read_int32()   # currentLeaderEpoch
            r.read_int64()   # fetchOffset
            r.read_int32()   # lastFetchedEpoch
            r.read_int64()   # logStartOffset
            r.read_int32()   # partitionMaxBytes
            r.read_uvarint() # tag buffer
            partitions.append(pid)
        r.read_uvarint()     # tag buffer (topic level)
        topics.append((uuid_bytes, partitions))
    return topics


def parse_metadata_body(r, version):
    """Parse Metadata v0/v1 request body (old-style encoding)."""
    count = r.read_int32()
    if count < 0:
        return None  # null = list all topics
    topics = []
    for _ in range(count):
        topics.append(r.read_nullable_string())
    return topics


# ─── Response builders ──────────────────────────────────────────────────

def build_api_versions_response(correlation_id, error_code):
    w = BinaryWriter()
    # Response header v0
    w.write_int32(correlation_id)
    w.write_int16(error_code)

    api_keys = [
        (1, 0, 16),   # Fetch
        (3, 0, 1),    # Metadata
        (18, 0, 4),   # ApiVersions
        (75, 0, 0),   # DescribeTopicPartitions
    ]

    if error_code != 0:
        w.write_uvarint(1)  # empty compact array
    else:
        w.write_uvarint(len(api_keys) + 1)
        for key, min_v, max_v in api_keys:
            w.write_int16(key)
            w.write_int16(min_v)
            w.write_int16(max_v)
            w.write_uvarint(0)  # tag buffer

    w.write_int32(0)        # throttle_time_ms
    w.write_uvarint(0)      # tag buffer
    return _frame(w.bytes())


def build_metadata_response(correlation_id, requested_topics, topics_by_name,
                            version):
    """Build Metadata v0 or v1 response (old-style encoding, header v0)."""
    w = BinaryWriter()
    # Response header v0
    w.write_int32(correlation_id)

    # Brokers (old-style array)
    w.write_int32(1)  # 1 broker
    w.write_int32(1)  # node_id
    w.write_old_string("localhost")
    w.write_int32(9092)
    if version >= 1:
        w.write_old_nullable_string(None)  # rack (v1+)

    if version >= 1:
        w.write_int32(1)  # controller_id (v1+)

    # Determine topic list
    if requested_topics is None:
        topic_list = sorted(topics_by_name.keys())
    else:
        topic_list = requested_topics

    w.write_int32(len(topic_list))
    for name in topic_list:
        info = topics_by_name.get(name)
        if info is None:
            w.write_int16(3)  # UNKNOWN_TOPIC_OR_PARTITION
            w.write_old_string(name)
            if version >= 1:
                w.write_int8(0)  # is_internal (v1+)
            w.write_int32(0)  # 0 partitions
        else:
            w.write_int16(0)  # no error
            w.write_old_string(name)
            if version >= 1:
                w.write_int8(0)  # is_internal (v1+)
            parts = sorted(info["partitions"].items())
            w.write_int32(len(parts))
            for pid, pinfo in parts:
                w.write_int16(0)  # error_code
                w.write_int32(pid)
                w.write_int32(pinfo["leader"])
                w.write_old_array_int32(pinfo["replicas"])
                w.write_old_array_int32(pinfo["isr"])

    return _frame(w.bytes())


def build_dtp_response(correlation_id, requested_names, topics_by_name):
    w = BinaryWriter()
    # Response header v1
    w.write_int32(correlation_id)
    w.write_uvarint(0)  # tag buffer
    # Body
    w.write_int32(0)  # throttle_time_ms
    w.write_uvarint(len(requested_names) + 1)  # topics array

    for name in requested_names:
        info = topics_by_name.get(name)
        if info is None:
            w.write_int16(3)  # error_code
            w.write_compact_string(name)
            w.write_raw(b'\x00' * 16)  # zeroed UUID
            w.write_int8(0)   # is_internal
            w.write_uvarint(1)  # partitions: empty
            w.write_int32(0)  # authorized_operations
            w.write_uvarint(0)  # tag buffer
        else:
            w.write_int16(0)  # error_code
            w.write_compact_string(name)
            w.write_raw(info["uuid"])
            w.write_int8(0)   # is_internal

            parts = sorted(info["partitions"].items())
            w.write_uvarint(len(parts) + 1)
            for pid, pinfo in parts:
                w.write_int16(0)          # error_code
                w.write_int32(pid)        # partition_index
                w.write_int32(pinfo["leader"])
                w.write_int32(pinfo["leader_epoch"])
                w.write_compact_array_int32(pinfo["replicas"])
                w.write_compact_array_int32(pinfo["isr"])
                w.write_compact_array_int32([])  # eligible_leader_replicas
                w.write_compact_array_int32([])  # last_known_elr
                w.write_compact_array_int32([])  # offline_replicas
                w.write_uvarint(0)  # tag buffer

            w.write_int32(0)  # authorized_operations
            w.write_uvarint(0)  # tag buffer

    w.write_int8(-1)    # next_cursor: null (0xff)
    w.write_uvarint(0)  # tag buffer
    return _frame(w.bytes())


def build_fetch_response(correlation_id, requested_topics, topics_by_uuid,
                         topics_by_name):
    w = BinaryWriter()
    # Response header v1
    w.write_int32(correlation_id)
    w.write_uvarint(0)  # tag buffer
    # Body
    w.write_int32(0)   # throttle_time_ms
    w.write_int16(0)   # error_code
    w.write_int32(0)   # session_id

    w.write_uvarint(len(requested_topics) + 1)  # responses array

    for uuid_bytes, partition_ids in requested_topics:
        w.write_raw(uuid_bytes)  # topic UUID
        topic_name = topics_by_uuid.get(uuid_bytes)

        w.write_uvarint(len(partition_ids) + 1)  # partitions array
        for pid in partition_ids:
            w.write_int32(pid)  # partition_index

            if topic_name is None:
                w.write_int16(100)   # error_code: UNKNOWN_TOPIC_ID
                w.write_int64(-1)    # highWatermark
                w.write_int64(-1)    # lastStableOffset
                w.write_int64(-1)    # logStartOffset
                w.write_uvarint(1)   # abortedTransactions: empty
                w.write_int32(-1)    # preferredReadReplica
                w.write_compact_nullable_bytes(None)  # records: null
                w.write_uvarint(0)   # tag buffer
            else:
                log_data = _read_partition_log(topic_name, pid)
                w.write_int16(0)     # error_code
                w.write_int64(0)     # highWatermark
                w.write_int64(0)     # lastStableOffset
                w.write_int64(0)     # logStartOffset
                w.write_uvarint(1)   # abortedTransactions: empty
                w.write_int32(-1)    # preferredReadReplica
                if log_data is None or len(log_data) == 0:
                    w.write_compact_nullable_bytes(b"")  # empty records
                else:
                    w.write_compact_nullable_bytes(log_data)
                w.write_uvarint(0)   # tag buffer

        w.write_uvarint(0)  # tag buffer (topic level)

    w.write_uvarint(0)  # tag buffer (body level)
    return _frame(w.bytes())


def _read_partition_log(topic_name, partition_id):
    path = os.path.join(KRAFT_LOG_DIR, f"{topic_name}-{partition_id}",
                        "00000000000000000000.log")
    if not os.path.exists(path):
        return None
    with open(path, 'rb') as f:
        return f.read()


def _frame(payload):
    return struct.pack('>i', len(payload)) + payload


# ─── Server ─────────────────────────────────────────────────────────────

def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


class KafkaBroker:
    def __init__(self):
        self.topics_by_name, self.topics_by_uuid = parse_cluster_metadata()

    def serve(self, port=9092):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('0.0.0.0', port))
        srv.listen(16)
        while True:
            conn, _ = srv.accept()
            t = threading.Thread(target=self._handle, args=(conn,), daemon=True)
            t.start()

    def _handle(self, conn):
        try:
            while True:
                hdr = recv_exact(conn, 4)
                msg_size = struct.unpack('>i', hdr)[0]
                data = recv_exact(conn, msg_size)
                r = BinaryReader(data)
                api_key, api_version, correlation_id = parse_request_header(r)

                if api_key == 18:
                    resp = self._handle_api_versions(api_version, correlation_id)
                elif api_key == 3:
                    resp = self._handle_metadata(r, api_version, correlation_id)
                elif api_key == 75:
                    resp = self._handle_dtp(r, correlation_id)
                elif api_key == 1:
                    resp = self._handle_fetch(r, correlation_id)
                else:
                    continue

                conn.sendall(resp)
        except Exception:
            pass
        finally:
            conn.close()

    def _handle_api_versions(self, version, correlation_id):
        if version < 0 or version > 4:
            return build_api_versions_response(correlation_id, 35)
        return build_api_versions_response(correlation_id, 0)

    def _handle_metadata(self, r, version, correlation_id):
        topics = parse_metadata_body(r, version)
        return build_metadata_response(correlation_id, topics,
                                       self.topics_by_name, version)

    def _handle_dtp(self, r, correlation_id):
        names = parse_dtp_body(r)
        return build_dtp_response(correlation_id, names, self.topics_by_name)

    def _handle_fetch(self, r, correlation_id):
        topics = parse_fetch_body(r)
        return build_fetch_response(correlation_id, topics,
                                    self.topics_by_uuid, self.topics_by_name)


if __name__ == "__main__":
    broker = KafkaBroker()
    broker.serve()
