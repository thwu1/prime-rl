#!/usr/bin/env python3
"""Generate session artifacts for the SCTP forensic analysis task.

Creates:
  /app/handshake.pcap     - SCTP INIT/INIT-ACK exchange (pcap format)
  /app/dcep_payloads.bin  - Binary DCEP DATA_CHANNEL_OPEN messages
  /app/session_trace.json - SACK computation event trace
"""

import struct
import json


def ip_checksum(header_bytes):
    if len(header_bytes) % 2:
        header_bytes += b'\x00'
    total = 0
    for i in range(0, len(header_bytes), 2):
        total += struct.unpack('!H', header_bytes[i:i+2])[0]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def crc32c(data):
    """CRC-32C (Castagnoli) used by SCTP checksums."""
    table = [0] * 256
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x82F63B78
            else:
                crc >>= 1
        table[i] = crc
    crc = 0xFFFFFFFF
    for byte in data:
        crc = table[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


def build_ip_packet(src_ip, dst_ip, payload):
    total_length = 20 + len(payload)
    header = struct.pack('!BBHHHBBH4s4s',
        0x45, 0, total_length, 1, 0x4000, 64, 132, 0, src_ip, dst_ip)
    chk = ip_checksum(header)
    header = header[:10] + struct.pack('!H', chk) + header[12:]
    return header + payload


def build_sctp_packet(src_port, dst_port, vtag, chunks_data):
    header = struct.pack('!HHI', src_port, dst_port, vtag)
    packet_no_cksum = header + b'\x00\x00\x00\x00' + chunks_data
    cksum = crc32c(packet_no_cksum)
    return header + struct.pack('<I', cksum) + chunks_data


def build_init_chunk(init_tag, a_rwnd, os_val, mis, initial_tsn):
    payload = struct.pack('!IIHHI', init_tag, a_rwnd, os_val, mis, initial_tsn)
    payload += struct.pack('!HH', 0xC000, 4)  # Forward-TSN-Supported
    chunk_len = 4 + len(payload)
    chunk = struct.pack('!BBH', 1, 0, chunk_len) + payload
    while len(chunk) % 4:
        chunk += b'\x00'
    return chunk


def build_init_ack_chunk(init_tag, a_rwnd, os_val, mis, initial_tsn, cookie):
    payload = struct.pack('!IIHHI', init_tag, a_rwnd, os_val, mis, initial_tsn)
    cookie_len = 4 + len(cookie)
    cookie_param = struct.pack('!HH', 7, cookie_len) + cookie
    while len(cookie_param) % 4:
        cookie_param += b'\x00'
    payload += cookie_param
    payload += struct.pack('!HH', 0xC000, 4)  # Forward-TSN-Supported
    chunk_len = 4 + len(payload)
    chunk = struct.pack('!BBH', 2, 0, chunk_len) + payload
    while len(chunk) % 4:
        chunk += b'\x00'
    return chunk


def write_pcap(filename, packets):
    header = struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 101)
    with open(filename, 'wb') as f:
        f.write(header)
        for i, pkt_data in enumerate(packets):
            pkt_header = struct.pack('<IIII', i, 0, len(pkt_data), len(pkt_data))
            f.write(pkt_header + pkt_data)


def build_dcep_open(channel_type, priority, reliability_param, label, protocol=""):
    label_bytes = label.encode('utf-8')
    proto_bytes = protocol.encode('utf-8')
    return struct.pack('!BBHIHH',
        0x03, channel_type, priority, reliability_param,
        len(label_bytes), len(proto_bytes)
    ) + label_bytes + proto_bytes


def main():
    src_ip = struct.pack('!BBBB', 10, 0, 0, 1)
    dst_ip = struct.pack('!BBBB', 10, 0, 0, 2)

    # Packet 1: INIT (A -> B)
    init_chunk = build_init_chunk(
        init_tag=0x4E17A2C0, a_rwnd=65535, os_val=16, mis=16,
        initial_tsn=0xFFFFFFF0)
    sctp_init = build_sctp_packet(5000, 5001, 0, init_chunk)
    ip_init = build_ip_packet(src_ip, dst_ip, sctp_init)

    # Packet 2: INIT-ACK (B -> A)
    cookie = bytes(range(16))
    init_ack_chunk = build_init_ack_chunk(
        init_tag=0x7D3B5E90, a_rwnd=131072, os_val=16, mis=16,
        initial_tsn=3000, cookie=cookie)
    sctp_init_ack = build_sctp_packet(5001, 5000, 0x4E17A2C0, init_ack_chunk)
    ip_init_ack = build_ip_packet(dst_ip, src_ip, sctp_init_ack)

    write_pcap('/app/handshake.pcap', [ip_init, ip_init_ack])

    # DCEP DATA_CHANNEL_OPEN payloads
    channels = [
        (0, build_dcep_open(0x00, 0, 0, "control")),
        (1, build_dcep_open(0x81, 128, 3, "sensor-feed")),
        (2, build_dcep_open(0x02, 64, 2000, "video-meta")),
        (3, build_dcep_open(0x80, 256, 0, "bulk", "binary")),
    ]
    with open('/app/dcep_payloads.bin', 'wb') as f:
        for stream_id, payload in channels:
            f.write(struct.pack('!HH', stream_id, len(payload)))
            f.write(payload)

    # Session trace for SACK computation
    trace = {
        "initial_tsn": 4294967280,
        "events": [
            {"type": "data_received", "tsn": 4294967280, "stream_id": 0, "ssn": 0},
            {"type": "compute_sack", "id": "s1"},

            {"type": "data_received", "tsn": 4294967282, "stream_id": 0, "ssn": 2},
            {"type": "compute_sack", "id": "s2"},

            {"type": "data_received", "tsn": 4294967284, "stream_id": 1, "ssn": 1},
            {"type": "data_received", "tsn": 4294967285, "stream_id": 2, "ssn": 1},
            {"type": "compute_sack", "id": "s3"},

            {"type": "data_received", "tsn": 4294967281, "stream_id": 0, "ssn": 1},
            {"type": "compute_sack", "id": "s4"},

            {"type": "data_received", "tsn": 4294967287, "stream_id": 1, "ssn": 2},
            {"type": "data_received", "tsn": 4294967289, "stream_id": 2, "ssn": 2},
            {"type": "compute_sack", "id": "s5"},

            {"type": "data_received", "tsn": 4294967285, "stream_id": 2, "ssn": 1},
            {"type": "compute_sack", "id": "s6"},

            {"type": "data_received", "tsn": 4294967283, "stream_id": 1, "ssn": 0},
            {"type": "compute_sack", "id": "s7"},

            {"type": "data_received", "tsn": 4294967291, "stream_id": 3, "ssn": 0},
            {"type": "data_received", "tsn": 4294967293, "stream_id": 1, "ssn": 3},
            {"type": "data_received", "tsn": 4294967295, "stream_id": 2, "ssn": 3},
            {"type": "data_received", "tsn": 1, "stream_id": 0, "ssn": 3},
            {"type": "compute_sack", "id": "s8"},

            {"type": "forward_tsn", "id": "f1", "new_cumulative_tsn": 4294967294,
             "streams": [{"stream_id": 1, "ssn": 3}, {"stream_id": 3, "ssn": 0}]},
            {"type": "compute_sack", "id": "s9"},

            {"type": "data_received", "tsn": 0, "stream_id": 3, "ssn": 1},
            {"type": "compute_sack", "id": "s10"},

            {"type": "data_received", "tsn": 5, "stream_id": 1, "ssn": 4},
            {"type": "data_received", "tsn": 3, "stream_id": 0, "ssn": 4},
            {"type": "data_received", "tsn": 7, "stream_id": 2, "ssn": 4},
            {"type": "compute_sack", "id": "s11"},

            {"type": "data_received", "tsn": 2, "stream_id": 3, "ssn": 2},
            {"type": "compute_sack", "id": "s12"},

            {"type": "forward_tsn", "id": "f2", "new_cumulative_tsn": 6,
             "streams": [{"stream_id": 1, "ssn": 4}]},
            {"type": "compute_sack", "id": "s13"},

            {"type": "data_received", "tsn": 7, "stream_id": 2, "ssn": 4},
            {"type": "compute_sack", "id": "s14"},

            {"type": "data_received", "tsn": 9, "stream_id": 0, "ssn": 5},
            {"type": "data_received", "tsn": 8, "stream_id": 1, "ssn": 5},
            {"type": "compute_sack", "id": "s15"},
        ]
    }
    with open('/app/session_trace.json', 'w') as f:
        json.dump(trace, f, indent=2)


if __name__ == '__main__':
    main()
