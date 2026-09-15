#!/usr/bin/env python3
"""Generate forensic artifacts for the QUIC connection forensics task."""
import struct
import json
import os


def ip_checksum(header):
    """Compute IPv4 header checksum."""
    if len(header) % 2:
        header = header + b'\x00'
    s = 0
    for i in range(0, len(header), 2):
        s += (header[i] << 8) | header[i + 1]
    while s >> 16:
        s = (s & 0xffff) + (s >> 16)
    return (~s) & 0xffff


def make_packet(src_ip, dst_ip, src_port, dst_port, payload, pkt_id=1):
    """Build Ethernet + IPv4 + UDP packet wrapping a QUIC payload."""
    if src_ip == '10.0.0.1':
        eth_src = b'\x02\x00\x00\x00\x00\x01'
        eth_dst = b'\x02\x00\x00\x00\x00\x02'
    else:
        eth_src = b'\x02\x00\x00\x00\x00\x02'
        eth_dst = b'\x02\x00\x00\x00\x00\x01'
    eth = eth_dst + eth_src + struct.pack('>H', 0x0800)

    src_bytes = bytes(int(x) for x in src_ip.split('.'))
    dst_bytes = bytes(int(x) for x in dst_ip.split('.'))
    udp_len = 8 + len(payload)
    ip_total = 20 + udp_len

    ip_hdr = struct.pack('>BBHHHBBH4s4s',
                         0x45, 0x00, ip_total, pkt_id, 0x4000,
                         64, 17, 0, src_bytes, dst_bytes)
    cksum = ip_checksum(ip_hdr)
    ip_hdr = struct.pack('>BBHHHBBH4s4s',
                         0x45, 0x00, ip_total, pkt_id, 0x4000,
                         64, 17, cksum, src_bytes, dst_bytes)

    udp = struct.pack('>HHHH', src_port, dst_port, udp_len, 0)
    return eth + ip_hdr + udp + payload


def write_pcap(path, packets):
    """Write a pcap file. packets: list of (ts_sec, ts_usec, raw_bytes)."""
    with open(path, 'wb') as f:
        f.write(struct.pack('<IHHiIII',
                            0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for ts_sec, ts_usec, pkt in packets:
            pkt_len = len(pkt)
            f.write(struct.pack('<IIII', ts_sec, ts_usec, pkt_len, pkt_len))
            f.write(pkt)


# --- QUIC packet hex data ---
initial_hex = ('c300000001088394c8f03e51570808f067a5502a4262b500360000'
               '0002000102030405060708090a0b0c0d0e0f10111213141516171'
               '8191a1b1c1d1e1f202122232425262728292a2b2c2d2e2f3031')

handshake_hex = ('e10000000108f067a5502a4262b508a1b2c3d4e5f6a7b82a0000'
                 'aabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabb'
                 'ccddaabbccddaabbccddaabbccdd')

zerortt_hex = ('d00000000108a1b2c3d4e5f6a7b808f067a5502a4262b51f0011'
               '223344556677889900112233445566778899001122334455667'
               '7889900')

vn_hex = ('bf0000000008f067a5502a4262b5088394c8f03e51570800000001'
          'ff00001d')

# Build pcap
pkt1 = make_packet('10.0.0.1', '10.0.0.2', 54321, 443,
                   bytes.fromhex(initial_hex), 1)
pkt2 = make_packet('10.0.0.2', '10.0.0.1', 443, 54321,
                   bytes.fromhex(handshake_hex), 2)
pkt3 = make_packet('10.0.0.1', '10.0.0.2', 54321, 443,
                   bytes.fromhex(zerortt_hex), 3)
pkt4 = make_packet('10.0.0.2', '10.0.0.1', 443, 54321,
                   bytes.fromhex(vn_hex), 4)

os.makedirs('/app/captures', exist_ok=True)
write_pcap('/app/captures/connection.pcap', [
    (1718100000, 0,     pkt1),
    (1718100000, 1000,  pkt2),
    (1718100000, 2000,  pkt3),
    (1718100000, 10000, pkt4),
])

# --- Transport parameters (hex blobs) ---
os.makedirs('/app/params', exist_ok=True)
with open('/app/params/server_tp.hex', 'w') as f:
    f.write('00088394c8f03e51570801048000753002100123456789abcdef'
            '0123456789abcdef030245c0040480a000000504800400000604'
            '80040000070480040000080240640901030a01030b01190c000e'
            '0102409702cafe0f08a1b2c3d4e5f6a7b8')
with open('/app/params/client_tp.hex', 'w') as f:
    f.write('01048000ea60030245c0040480f0000005048008000006048008'
            '0000070480080000080240c80901320a01030b04800040000e01'
            '040f08f067a5502a4262b5')

# --- Qlog traces ---
os.makedirs('/app/qlogs', exist_ok=True)

server_qlog = {
    "qlog_version": "0.4",
    "qlog_format": "JSON",
    "traces": [{
        "vantage_point": {"name": "quic-server", "type": "server"},
        "title": "QUIC server trace",
        "configuration": {"time_offset": 0.0},
        "events": [
            {"time": 0.0, "name": "connectivity:connection_started", "data": {
                "ip_version": "ipv4", "src_ip": "10.0.0.2",
                "dst_ip": "10.0.0.1", "src_port": 443, "dst_port": 54321,
                "quic_version": "1"
            }},
            {"time": 0.0, "name": "transport:parameters_set", "data": {
                "owner": "local",
                "original_destination_connection_id": "8394c8f03e515708",
                "max_idle_timeout": 30000,
                "stateless_reset_token": "0123456789abcdef0123456789abcdef",
                "max_udp_payload_size": 1472,
                "initial_max_data": 10485760,
                "initial_max_stream_data_bidi_local": 262144,
                "initial_max_stream_data_bidi_remote": 262144,
                "initial_max_stream_data_uni": 262144,
                "initial_max_streams_bidi": 100,
                "initial_max_streams_uni": 3,
                "ack_delay_exponent": 3,
                "max_ack_delay": 25,
                "disable_active_migration": True,
                "active_connection_id_limit": 2,
                "initial_source_connection_id": "a1b2c3d4e5f6a7b8"
            }},
            {"time": 0.5, "name": "transport:packet_received", "data": {
                "header": {"packet_type": "initial", "packet_number": 2,
                           "dcid": "8394c8f03e515708",
                           "scid": "f067a5502a4262b5"}
            }},
            {"time": 0.5, "name": "transport:parameters_received", "data": {
                "owner": "remote",
                "max_idle_timeout": 60000, "max_udp_payload_size": 1472,
                "initial_max_data": 15728640,
                "initial_max_stream_data_bidi_local": 524288,
                "initial_max_stream_data_bidi_remote": 524288,
                "initial_max_stream_data_uni": 524288,
                "initial_max_streams_bidi": 200,
                "initial_max_streams_uni": 50,
                "ack_delay_exponent": 3, "max_ack_delay": 16384,
                "active_connection_id_limit": 4,
                "initial_source_connection_id": "f067a5502a4262b5"
            }},
            {"time": 0.6, "name": "transport:packet_sent", "data": {
                "header": {"packet_type": "handshake", "packet_number": 0,
                           "dcid": "f067a5502a4262b5",
                           "scid": "a1b2c3d4e5f6a7b8"},
                "frames": [{"frame_type": "crypto", "offset": 0,
                             "length": 300}]
            }},
            {"time": 0.7, "name": "connectivity:connection_closed", "data": {
                "owner": "local", "trigger": "error",
                "connection_code": "TRANSPORT_PARAMETER_ERROR",
                "reason": "invalid max_ack_delay value from peer"
            }},
            {"time": 0.7, "name": "recovery:metrics_updated", "data": {
                "min_rtt": 0.5, "smoothed_rtt": 0.5, "latest_rtt": 0.5,
                "rtt_variance": 0.0, "congestion_window": 14720,
                "bytes_in_flight": 0
            }}
        ]
    }]
}

client_qlog = {
    "qlog_version": "0.4",
    "qlog_format": "JSON",
    "traces": [{
        "vantage_point": {"name": "quic-client", "type": "client"},
        "title": "QUIC client trace",
        "configuration": {"time_offset": 0.0},
        "events": [
            {"time": 0.0, "name": "connectivity:connection_started", "data": {
                "ip_version": "ipv4", "src_ip": "10.0.0.1",
                "dst_ip": "10.0.0.2", "src_port": 54321, "dst_port": 443,
                "quic_version": "1"
            }},
            {"time": 0.0, "name": "transport:parameters_set", "data": {
                "owner": "local",
                "max_idle_timeout": 60000, "max_udp_payload_size": 1472,
                "initial_max_data": 15728640,
                "initial_max_stream_data_bidi_local": 524288,
                "initial_max_stream_data_bidi_remote": 524288,
                "initial_max_stream_data_uni": 524288,
                "initial_max_streams_bidi": 200,
                "initial_max_streams_uni": 50,
                "ack_delay_exponent": 3, "max_ack_delay": 16384,
                "active_connection_id_limit": 4,
                "initial_source_connection_id": "f067a5502a4262b5"
            }},
            {"time": 0.1, "name": "transport:packet_sent", "data": {
                "header": {"packet_type": "initial", "packet_number": 2,
                           "dcid": "8394c8f03e515708",
                           "scid": "f067a5502a4262b5"},
                "frames": [{"frame_type": "crypto", "offset": 0,
                             "length": 253}]
            }},
            {"time": 0.2, "name": "transport:packet_sent", "data": {
                "header": {"packet_type": "0rtt", "packet_number": 0,
                           "dcid": "a1b2c3d4e5f6a7b8",
                           "scid": "f067a5502a4262b5"},
                "frames": [{"frame_type": "stream", "stream_id": 0,
                             "offset": 0, "length": 45, "fin": False}]
            }},
            {"time": 0.6, "name": "transport:packet_received", "data": {
                "header": {"packet_type": "handshake", "packet_number": 0,
                           "dcid": "f067a5502a4262b5",
                           "scid": "a1b2c3d4e5f6a7b8"}
            }},
            {"time": 0.6, "name": "transport:parameters_received", "data": {
                "owner": "remote",
                "original_destination_connection_id": "8394c8f03e515708",
                "max_idle_timeout": 30000,
                "stateless_reset_token": "0123456789abcdef0123456789abcdef",
                "max_udp_payload_size": 1472,
                "initial_max_data": 10485760,
                "initial_max_stream_data_bidi_local": 262144,
                "initial_max_stream_data_bidi_remote": 262144,
                "initial_max_stream_data_uni": 262144,
                "initial_max_streams_bidi": 100,
                "initial_max_streams_uni": 3,
                "ack_delay_exponent": 3, "max_ack_delay": 25,
                "disable_active_migration": True,
                "active_connection_id_limit": 2,
                "initial_source_connection_id": "a1b2c3d4e5f6a7b8"
            }},
            {"time": 1.2, "name": "connectivity:connection_closed", "data": {
                "owner": "remote", "trigger": "error",
                "connection_code": "TRANSPORT_PARAMETER_ERROR",
                "reason": "peer closed connection"
            }},
            {"time": 1.2, "name": "recovery:metrics_updated", "data": {
                "min_rtt": 0.5, "smoothed_rtt": 0.6, "latest_rtt": 0.6,
                "rtt_variance": 0.05, "congestion_window": 14720,
                "bytes_in_flight": 0
            }}
        ]
    }]
}

with open('/app/qlogs/server.qlog', 'w') as f:
    json.dump(server_qlog, f, indent=2)
with open('/app/qlogs/client.qlog', 'w') as f:
    json.dump(client_qlog, f, indent=2)

print("Artifacts generated successfully")
