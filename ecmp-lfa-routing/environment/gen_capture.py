#!/usr/bin/env python3
"""Generate NLSP heartbeat packet capture for network audit task."""
import struct
import os

def ip_checksum(data):
    if len(data) % 2:
        data = data + b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) | data[i + 1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF

def make_udp_ip_eth(src_last, dst_last, payload, ts_sec, ts_usec, sport=47891, dport=47891):
    eth = (b'\xff\xff\xff\xff\xff\xff'
           + bytes([0x02, 0x00, 0x00, 0x00, 0x00, src_last])
           + b'\x08\x00')
    udp_len = 8 + len(payload)
    udp = struct.pack('!HHHH', sport, dport, udp_len, 0)
    ip_total = 20 + udp_len
    ip_hdr = bytearray(20)
    struct.pack_into('!BBHHHBBH', ip_hdr, 0,
                     0x45, 0x00, ip_total, 0, 0x4000, 64, 17, 0)
    ip_hdr[12:16] = bytes([10, 0, 0, src_last])
    ip_hdr[16:20] = bytes([10, 0, 0, dst_last])
    cs = ip_checksum(bytes(ip_hdr))
    struct.pack_into('!H', ip_hdr, 10, cs)
    frame = eth + bytes(ip_hdr) + udp + payload
    rec_hdr = struct.pack('<IIII', ts_sec, ts_usec, len(frame), len(frame))
    return rec_hdr + frame

def make_nlsp(flags, src_id, dst_id, cost, seq_num, timestamp):
    return struct.pack('!2sBBBBHII', b'NL', 1, flags, src_id, dst_id, cost, seq_num, timestamp)

ROUTERS = {'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5, 'F': 6}
LINKS = [
    ('A', 'B', 3), ('B', 'A', 3),
    ('A', 'D', 1), ('D', 'A', 1),
    ('A', 'F', 6), ('F', 'A', 6),
    ('B', 'C', 4), ('C', 'B', 4),
    ('B', 'E', 1), ('E', 'B', 1),
    ('C', 'D', 1), ('D', 'C', 1),
    ('D', 'E', 1), ('E', 'D', 1),
    ('E', 'F', 2), ('F', 'E', 2),
]

BASE_TS = 1718300000
os.makedirs('/app', exist_ok=True)
data = bytearray()
data += struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)

seq = 1
for rnd in range(5):
    ts = BASE_TS + rnd * 10
    for src_name, dst_name, cost in LINKS:
        sid, did = ROUTERS[src_name], ROUTERS[dst_name]
        payload = make_nlsp(0x01, sid, did, cost, seq, ts)
        data += make_udp_ip_eth(sid, did, payload, ts, rnd * 50000 + seq * 1000)
        seq += 1

    if rnd == 1:
        for i in range(3):
            bad = struct.pack('!2sBBBBHII', b'XX', 1, 0x01, 1, 2, 999, 90000 + i, ts)
            data += make_udp_ip_eth(1, 2, bad, ts, 900000 + i * 1000)

    if rnd == 2:
        dns = b'\x00\x01\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x03www\x06google\x03com\x00\x00\x01\x00\x01'
        for i in range(4):
            data += make_udp_ip_eth(1, 10, dns, ts, 800000 + i * 5000, sport=12345, dport=53)

with open('/app/network_capture.pcap', 'wb') as f:
    f.write(bytes(data))

print(f'Generated pcap: {seq - 1} NLSP packets + noise')
