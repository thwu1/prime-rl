#!/usr/bin/env python3

"""Generate a reference TCP packet capture showing retransmission behavior.

Creates /app/reference/capture.pcap with a TCP session demonstrating:
- Three-way handshake
- Bulk data transfer (10 segments of 1000 bytes)
- Packet loss causing duplicate ACKs
- Fast retransmit triggered by triple duplicate ACK
- Cumulative ACK after out-of-order reassembly
- Four-way connection teardown
"""

import struct
import os

PCAP_MAGIC = 0xa1b2c3d4
LINKTYPE_RAW = 101  # Raw IPv4 (no link layer)

CLIENT_IP = bytes([10, 0, 0, 1])
SERVER_IP = bytes([10, 0, 0, 2])
CPORT = 5000
SPORT = 80


def inet_checksum(data):
    """Internet checksum per RFC 1071."""
    if len(data) % 2:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) | data[i + 1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def make_tcp(src_port, dst_port, seq, ack, flags, window, data, src_ip, dst_ip):
    """Build TCP header + data with correct checksum."""
    flag_bits = 0
    if 'S' in flags:
        flag_bits |= 0x02
    if 'A' in flags:
        flag_bits |= 0x10
    if 'F' in flags:
        flag_bits |= 0x01
    if 'P' in flags:
        flag_bits |= 0x08

    hdr = struct.pack('!HHIIBBHHH',
                      src_port, dst_port,
                      seq & 0xFFFFFFFF, ack & 0xFFFFFFFF,
                      5 << 4, flag_bits, window, 0, 0)
    pseudo = struct.pack('!4s4sBBH',
                         src_ip, dst_ip, 0, 6, len(hdr) + len(data))
    cs = inet_checksum(pseudo + hdr + data)
    hdr = struct.pack('!HHIIBBHHH',
                      src_port, dst_port,
                      seq & 0xFFFFFFFF, ack & 0xFFFFFFFF,
                      5 << 4, flag_bits, window, cs, 0)
    return hdr + data


def make_ipv4(src, dst, payload, ident=0):
    """Build IPv4 packet with correct header checksum."""
    total_len = 20 + len(payload)
    hdr = struct.pack('!BBHHHBBH4s4s',
                      0x45, 0, total_len, ident, 0x4000, 64, 6, 0, src, dst)
    cs = inet_checksum(hdr)
    hdr = struct.pack('!BBHHHBBH4s4s',
                      0x45, 0, total_len, ident, 0x4000, 64, 6, cs, src, dst)
    return hdr + payload


packets = []
pkt_id = 0


def pkt(ts_ms, src_ip, dst_ip, sp, dp, seq, ack, flags, win=65535, data=b''):
    """Create and record a packet."""
    global pkt_id
    tcp = make_tcp(sp, dp, seq, ack, flags, win, data, src_ip, dst_ip)
    ip = make_ipv4(src_ip, dst_ip, tcp, ident=pkt_id)
    packets.append((ts_ms * 1000, ip))  # Store as microseconds
    pkt_id += 1


# --- Three-way handshake ---
pkt(0,    CLIENT_IP, SERVER_IP, CPORT, SPORT, 100, 0,   'S')
pkt(50,   SERVER_IP, CLIENT_IP, SPORT, CPORT, 200, 101, 'SA')
pkt(100,  CLIENT_IP, SERVER_IP, CPORT, SPORT, 101, 201, 'A')

# --- Data transfer: server sends 10 x 1000-byte segments ---
DATA = b'\x41' * 1000  # 'A' repeated

for i in range(10):
    seq = 201 + i * 1000
    ts = 150 + i * 5
    if i == 3:
        continue  # Segment 4 (seq=3201) is LOST
    pkt(ts, SERVER_IP, CLIENT_IP, SPORT, CPORT, seq, 101, 'PA', data=DATA)

# --- Client ACKs ---
# Segments 0-2 arrive in order, ACKed normally
pkt(255, CLIENT_IP, SERVER_IP, CPORT, SPORT, 101, 1201, 'A')  # ACK seg 0
pkt(260, CLIENT_IP, SERVER_IP, CPORT, SPORT, 101, 2201, 'A')  # ACK seg 1
pkt(265, CLIENT_IP, SERVER_IP, CPORT, SPORT, 101, 3201, 'A')  # ACK seg 2

# Segment 3 (seq=3201) was lost. Segments 4-6 arrive out of order.
# Client sends duplicate ACKs since gap at 3201.
pkt(270, CLIENT_IP, SERVER_IP, CPORT, SPORT, 101, 3201, 'A')  # dup ACK 1 (seg 4)
pkt(275, CLIENT_IP, SERVER_IP, CPORT, SPORT, 101, 3201, 'A')  # dup ACK 2 (seg 5)
pkt(280, CLIENT_IP, SERVER_IP, CPORT, SPORT, 101, 3201, 'A')  # dup ACK 3 (seg 6) -> fast retransmit

# --- Fast retransmit of segment 3 ---
pkt(285, SERVER_IP, CLIENT_IP, SPORT, CPORT, 3201, 101, 'PA', data=DATA)

# Client reassembles and sends cumulative ACK covering segs 3-7
pkt(340, CLIENT_IP, SERVER_IP, CPORT, SPORT, 101, 8201, 'A')

# ACKs for remaining segments 8-9
pkt(345, CLIENT_IP, SERVER_IP, CPORT, SPORT, 101, 9201, 'A')
pkt(350, CLIENT_IP, SERVER_IP, CPORT, SPORT, 101, 10201, 'A')

# --- Four-way teardown ---
pkt(400, SERVER_IP, CLIENT_IP, SPORT, CPORT, 10201, 101, 'FA')
pkt(450, CLIENT_IP, SERVER_IP, CPORT, SPORT, 101, 10202, 'A')
pkt(460, CLIENT_IP, SERVER_IP, CPORT, SPORT, 101, 10202, 'FA')
pkt(510, SERVER_IP, CLIENT_IP, SPORT, CPORT, 10202, 102, 'A')

# --- Write pcap file ---
os.makedirs('/app/reference', exist_ok=True)
with open('/app/reference/capture.pcap', 'wb') as f:
    # Global header
    f.write(struct.pack('<IHHiIII',
                        PCAP_MAGIC, 2, 4, 0, 0, 65535, LINKTYPE_RAW))
    # Packet records
    for ts_us, raw_pkt in packets:
        ts_sec = ts_us // 1000000
        ts_usec = ts_us % 1000000
        f.write(struct.pack('<IIII', ts_sec, ts_usec, len(raw_pkt), len(raw_pkt)))
        f.write(raw_pkt)

print(f"Generated /app/reference/capture.pcap with {len(packets)} packets")
