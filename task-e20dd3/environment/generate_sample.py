#!/usr/bin/env python3
"""Generate a single-packet sample pcap for development testing."""
import struct
import socket

def ip_checksum(data):
    if len(data) % 2:
        data += b'\x00'
    words = struct.unpack('!%dH' % (len(data) // 2), data)
    s = sum(words)
    s = (s >> 16) + (s & 0xffff)
    s += (s >> 16)
    return ~s & 0xffff

# Ethernet: broadcast dst, arbitrary src, EtherType=IPv4
eth = b'\xff\xff\xff\xff\xff\xff\x00\x11\x22\x33\x44\x55\x08\x00'

# IPv4: ver=4, ihl=5(20 bytes), tos=0, total_len=60, id=0xfefe,
#        flags=DF, ttl=64, proto=TCP(6)
#        src=192.168.1.10, dst=93.184.216.34
ip = struct.pack('!BBHHHBBH4s4s',
    0x45, 0, 60, 0xfefe, 0x4000, 64, 6, 0,
    socket.inet_aton('192.168.1.10'),
    socket.inet_aton('93.184.216.34'))
cs = ip_checksum(ip)
ip = ip[:10] + struct.pack('!H', cs) + ip[12:]

# TCP: src=49152, dst=80, seq=100, ack=0
#      doff=10 (40 bytes = 20 header + 20 options), SYN, window=14600
tcp = struct.pack('!HHIIHHHH', 49152, 80, 100, 0, 0xa002, 14600, 0, 0)

# TCP options (20 bytes):
#   MSS(1460) + SACK_OK + Timestamp(65536,0) + NOP + WindowScale(7)
opts = (b'\x02\x04\x05\xb4'
        b'\x04\x02'
        b'\x08\x0a\x00\x01\x00\x00\x00\x00\x00\x00'
        b'\x01'
        b'\x03\x03\x07')

pkt = eth + ip + tcp + opts

with open('/app/sample.pcap', 'wb') as f:
    # pcap global header (little-endian)
    f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
    # packet record header
    f.write(struct.pack('<IIII', 1000000, 0, len(pkt), len(pkt)))
    f.write(pkt)

# Expected signature: 4:64:0:1460:mss*10,7:mss,sok,ts,nop,ws:df,id+:0
# Expected OS: s:Linux:4.x:
