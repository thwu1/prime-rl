#!/usr/bin/env python3
"""Generate PCAP capture files for IPv6 security audit task."""
import struct
import socket
import os

PCAP_DIR = '/app/captures'
PCAP_MAGIC = 0xa1b2c3d4
PCAP_VER_MAJ = 2
PCAP_VER_MIN = 4
PCAP_SNAPLEN = 65535
LINKTYPE_RAW = 101


def write_pcap(filepath, packets):
    with open(filepath, 'wb') as f:
        f.write(struct.pack('<IHHiIII',
                            PCAP_MAGIC, PCAP_VER_MAJ, PCAP_VER_MIN,
                            0, 0, PCAP_SNAPLEN, LINKTYPE_RAW))
        for i, pkt in enumerate(packets):
            f.write(struct.pack('<IIII',
                                1700000000 + i, i * 1000,
                                len(pkt), len(pkt)))
            f.write(pkt)


def v6(addr_str):
    return socket.inet_pton(socket.AF_INET6, addr_str)


def ipv6(payload_len, nh, src, dst, hop=64, ver=6):
    w = (ver << 28)
    return struct.pack('!IHBB', w, payload_len, nh, hop) + v6(src) + v6(dst)


def tcp_syn(sp=12345, dp=80):
    return struct.pack('!HHIIHHHH',
                       sp, dp, 1000, 0,
                       (5 << 12) | 0x02, 65535, 0, 0)


def frag_hdr(nh, offset, m, ident):
    off_m = (offset << 3) | (m & 1)
    return struct.pack('!BBHI', nh, 0, off_m, ident)


def hbh_opt(nh, hel=0):
    total = (hel + 1) * 8
    hdr = struct.pack('BB', nh, hel)
    pad = total - 2
    if pad <= 1:
        hdr += bytes(pad)
    else:
        hdr += struct.pack('BB', 1, pad - 2) + bytes(pad - 2)
    return hdr


def dst_opt(nh, hel=0):
    return hbh_opt(nh, hel)


def routing_hdr(nh, rtype, segleft, hel=0, addrs=None):
    total = (hel + 1) * 8
    hdr = struct.pack('BBBB', nh, hel, rtype, segleft)
    hdr += bytes(4)  # Reserved
    remaining = total - 8
    if addrs:
        for a in addrs:
            hdr += v6(a)
            remaining -= 16
    if remaining > 0:
        hdr += bytes(remaining)
    return hdr


os.makedirs(PCAP_DIR, exist_ok=True)

# === capture_01: Legitimate TCP over IPv6 (no extension headers) ===
t = tcp_syn()
write_pcap(f'{PCAP_DIR}/capture_01.pcap',
           [ipv6(len(t), 6, '2001:db8:a::1', '2001:db8:b::1') + t])

# === capture_02: Legitimate HBH + Destination Options + TCP ===
t = tcp_syn(23456, 443)
payload = hbh_opt(60) + dst_opt(6) + t   # HBH(NH=DST) + DST(NH=TCP) + TCP
write_pcap(f'{PCAP_DIR}/capture_02.pcap',
           [ipv6(len(payload), 0, '2001:db8:a::2', '2001:db8:b::2') + payload])

# === capture_03: Routing Header Type 0 — DEPRECATED by RFC 5095 ===
t = tcp_syn(34567, 22)
rh0 = routing_hdr(6, 0, 1, hel=2, addrs=['2001:db8:c::1'])
payload = rh0 + t
write_pcap(f'{PCAP_DIR}/capture_03.pcap',
           [ipv6(len(payload), 43, '2001:db8:a::3', '2001:db8:b::3') + payload])

# === capture_04: Overlapping fragments (evasion technique) ===
# Fragment 1: offset=0, M=1, 16 bytes data => covers [0,16)
# Fragment 2: offset=1 (8 bytes), M=0, 16 bytes data => covers [8,24) — overlap at [8,16)
d1 = tcp_syn(45678, 80)[:16]
f1 = frag_hdr(6, 0, 1, 0xDEAD0001) + d1
p1 = ipv6(len(f1), 44, '2001:db8:a::4', '2001:db8:b::4') + f1

d2 = bytes(16)
f2 = frag_hdr(6, 1, 0, 0xDEAD0001) + d2
p2 = ipv6(len(f2), 44, '2001:db8:a::4', '2001:db8:b::4') + f2
write_pcap(f'{PCAP_DIR}/capture_04.pcap', [p1, p2])

# === capture_05: Legitimate fragmented traffic (non-overlapping, complete) ===
# Fragment 1: offset=0, M=1, 24 bytes => [0,24)
# Fragment 2: offset=3 (24 bytes), M=0, 16 bytes => [24,40) — no overlap
d1 = tcp_syn() + bytes(4)     # 20 + 4 = 24 bytes (full TCP header + padding)
f1 = frag_hdr(6, 0, 1, 0xBEEF0001) + d1
p1 = ipv6(len(f1), 44, '2001:db8:a::5', '2001:db8:b::5') + f1

d2 = bytes(16)
f2 = frag_hdr(6, 3, 0, 0xBEEF0001) + d2
p2 = ipv6(len(f2), 44, '2001:db8:a::5', '2001:db8:b::5') + f2
write_pcap(f'{PCAP_DIR}/capture_05.pcap', [p1, p2])

# === capture_06: Oversized reassembly (offset*8 + data > 65535) ===
# offset=8190, 24 bytes data => 8190*8 + 24 = 65544 > 65535
d = bytes(24)
fh = frag_hdr(6, 8190, 0, 0xCAFE0001) + d
write_pcap(f'{PCAP_DIR}/capture_06.pcap',
           [ipv6(len(fh), 44, '2001:db8:a::6', '2001:db8:b::6') + fh])

# === capture_07: Hop-by-Hop NOT first extension header (RFC 8200 §4.1 violation) ===
# Chain: IPv6(NH=Routing) -> Routing(NH=HBH) -> HBH(NH=TCP) -> TCP
t = tcp_syn(56789, 8080)
payload = routing_hdr(0, 2, 0) + hbh_opt(6) + t
write_pcap(f'{PCAP_DIR}/capture_07.pcap',
           [ipv6(len(payload), 43, '2001:db8:a::7', '2001:db8:b::7') + payload])

# === capture_08: Duplicate Routing headers (RFC 8200 §4.1 violation) ===
# Chain: IPv6(NH=Routing) -> Routing(NH=Routing) -> Routing(NH=TCP) -> TCP
t = tcp_syn(11111, 443)
payload = routing_hdr(43, 2, 0) + routing_hdr(6, 2, 0) + t
write_pcap(f'{PCAP_DIR}/capture_08.pcap',
           [ipv6(len(payload), 43, '2001:db8:a::8', '2001:db8:b::8') + payload])

# === capture_09: Tiny fragment evasion ===
# First fragment with only 8 bytes of data — too small for TCP header (20 bytes)
# Classic firewall evasion: L4 flags not visible in first fragment
d = tcp_syn()[:8]
fh = frag_hdr(6, 0, 1, 0xFACE0001) + d
write_pcap(f'{PCAP_DIR}/capture_09.pcap',
           [ipv6(len(fh), 44, '2001:db8:a::9', '2001:db8:b::9') + fh])

# === capture_10: Legitimate ICMPv6 Neighbor Solicitation ===
# Type=135, Code=0, Checksum=0, Reserved=0, Target=2001:db8:b::1
icmp = struct.pack('!BBHI', 135, 0, 0, 0) + v6('2001:db8:b::1')
write_pcap(f'{PCAP_DIR}/capture_10.pcap',
           [ipv6(len(icmp), 58, 'fe80::1', 'ff02::1:ff00:1', hop=255) + icmp])

print(f"Generated 10 capture files in {PCAP_DIR}")
