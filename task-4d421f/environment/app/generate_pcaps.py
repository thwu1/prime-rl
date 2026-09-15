#!/usr/bin/env python3
"""Generate OSPF pcap files for conformance testing scenarios.

Uses raw struct packing (no external dependencies) to create valid
Ethernet/IP/OSPF pcap files that tshark can parse.
"""

import os
import struct

os.makedirs("/data/captures", exist_ok=True)


def ip_to_bytes(ip):
    return bytes(int(x) for x in ip.split('.'))


def compute_checksum(data):
    """Standard ones-complement checksum (IP/OSPF)."""
    if len(data) % 2:
        data = data + b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i + 1]
    while s >> 16:
        s = (s >> 16) + (s & 0xffff)
    return ~s & 0xffff


def build_ospf_hello(router_id, area, mask, hello_int, dead_int, priority,
                     dr, bdr, neighbors):
    """Build an OSPF Hello packet (header + body), return raw bytes."""
    # Hello body (RFC 2328 A.3.2)
    hello = struct.pack('!4sHBBI4s4s',
                        ip_to_bytes(mask),
                        hello_int,
                        0x02,      # Options: E-bit set
                        priority,
                        dead_int,
                        ip_to_bytes(dr),
                        ip_to_bytes(bdr))
    for nbr in neighbors:
        hello += ip_to_bytes(nbr)

    # OSPF header (RFC 2328 A.3.1) — 24 bytes
    ospf_len = 24 + len(hello)
    ospf_hdr = struct.pack('!BBH4s4sHH8s',
                           2,                   # Version
                           1,                   # Type: Hello
                           ospf_len,
                           ip_to_bytes(router_id),
                           ip_to_bytes(area),
                           0,                   # Checksum placeholder
                           0,                   # AuType: Null
                           b'\x00' * 8)          # Authentication

    full = ospf_hdr + hello
    # Checksum: over entire packet EXCLUDING 8-byte auth field (bytes 16-23)
    chk_data = full[:16] + full[24:]
    chksum = compute_checksum(chk_data)

    ospf_hdr = struct.pack('!BBH4s4sHH8s',
                           2, 1, ospf_len,
                           ip_to_bytes(router_id),
                           ip_to_bytes(area),
                           chksum,
                           0,
                           b'\x00' * 8)
    return ospf_hdr + hello


def build_ip_ospf(src, dst, ospf_payload):
    """Wrap OSPF payload in an IP header."""
    total_len = 20 + len(ospf_payload)
    hdr = struct.pack('!BBHHHBBH4s4s',
                      0x45,    # Version 4, IHL 5
                      0xc0,    # DSCP CS6
                      total_len,
                      0,       # Identification
                      0x4000,  # Flags: DF
                      1,       # TTL
                      89,      # Protocol: OSPF
                      0,       # Checksum placeholder
                      ip_to_bytes(src),
                      ip_to_bytes(dst))
    chksum = compute_checksum(hdr)
    hdr = struct.pack('!BBHHHBBH4s4s',
                      0x45, 0xc0, total_len, 0, 0x4000, 1, 89,
                      chksum,
                      ip_to_bytes(src),
                      ip_to_bytes(dst))
    return hdr + ospf_payload


def build_frame(src_mac_suffix, src_ip, dst_ip, ospf_payload):
    """Build Ethernet frame with IP + OSPF payload."""
    dst_mac = b'\x01\x00\x5e\x00\x00\x05'   # AllSPFRouters multicast
    src_mac = b'\x00\x00\x00\x00\x00' + bytes([src_mac_suffix])
    ip_pkt = build_ip_ospf(src_ip, dst_ip, ospf_payload)
    return dst_mac + src_mac + b'\x08\x00' + ip_pkt


def write_pcap(filename, packets):
    """Write a pcap file.  packets = list of (timestamp_float, frame_bytes)."""
    with open(filename, 'wb') as f:
        # Global header: LINKTYPE_ETHERNET (1)
        f.write(struct.pack('<IHHiIII',
                            0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for ts, data in packets:
            ts_sec = int(ts)
            ts_usec = int((ts - ts_sec) * 1_000_000)
            f.write(struct.pack('<IIII', ts_sec, ts_usec, len(data), len(data)))
            f.write(data)


ALLSPF = "224.0.0.5"
BASE_T = 1700000000

# ================================================================
# Scenario 1 — P2P adjacency formation (R3 <-> R4, point-to-point)
# ================================================================
pkts = []

# T+0  R3 Hello, empty neighbor list
ospf = build_ospf_hello("3.3.3.3", "0.0.0.0", "255.255.255.252",
                        10, 40, 1, "0.0.0.0", "0.0.0.0", [])
pkts.append((BASE_T, build_frame(0x03, "10.0.2.1", ALLSPF, ospf)))

# T+1  R4 Hello, empty neighbor list
ospf = build_ospf_hello("4.4.4.4", "0.0.0.0", "255.255.255.252",
                        10, 40, 1, "0.0.0.0", "0.0.0.0", [])
pkts.append((BASE_T + 1, build_frame(0x04, "10.0.2.2", ALLSPF, ospf)))

# T+10 R3 Hello, lists R4
ospf = build_ospf_hello("3.3.3.3", "0.0.0.0", "255.255.255.252",
                        10, 40, 1, "0.0.0.0", "0.0.0.0", ["4.4.4.4"])
pkts.append((BASE_T + 10, build_frame(0x03, "10.0.2.1", ALLSPF, ospf)))

# T+11 R4 Hello, lists R3
ospf = build_ospf_hello("4.4.4.4", "0.0.0.0", "255.255.255.252",
                        10, 40, 1, "0.0.0.0", "0.0.0.0", ["3.3.3.3"])
pkts.append((BASE_T + 11, build_frame(0x04, "10.0.2.2", ALLSPF, ospf)))

# T+20 R3 Hello, lists R4 (continued)
ospf = build_ospf_hello("3.3.3.3", "0.0.0.0", "255.255.255.252",
                        10, 40, 1, "0.0.0.0", "0.0.0.0", ["4.4.4.4"])
pkts.append((BASE_T + 20, build_frame(0x03, "10.0.2.1", ALLSPF, ospf)))

write_pcap("/data/captures/p2p_adjacency.pcap", pkts)

# ================================================================
# Scenario 2 — Broadcast network with DR/BDR election
# R1=DR (prio 100), R2=BDR (prio 50), R3=DROther (prio 10),
# R5=DROther (prio 5) on 10.0.1.0/24
# ================================================================
pkts = []

# Round 1 — initial Hellos, no neighbors yet, no DR elected
for i, (rid, ip, mac, prio) in enumerate([
    ("1.1.1.1", "10.0.1.1", 0x01, 100),
    ("2.2.2.2", "10.0.1.2", 0x02, 50),
    ("3.3.3.3", "10.0.1.3", 0x03, 10),
    ("5.5.5.5", "10.0.1.5", 0x05, 5),
]):
    ospf = build_ospf_hello(rid, "0.0.0.0", "255.255.255.0",
                            10, 40, prio, "0.0.0.0", "0.0.0.0", [])
    pkts.append((BASE_T + i * 0.5, build_frame(mac, ip, ALLSPF, ospf)))

# Round 2 — DR elected, full neighbor lists
nbr_sets = {
    "1.1.1.1": ["2.2.2.2", "3.3.3.3", "5.5.5.5"],
    "2.2.2.2": ["1.1.1.1", "3.3.3.3", "5.5.5.5"],
    "3.3.3.3": ["1.1.1.1", "2.2.2.2", "5.5.5.5"],
    "5.5.5.5": ["1.1.1.1", "2.2.2.2", "3.3.3.3"],
}
for i, (rid, ip, mac, prio) in enumerate([
    ("1.1.1.1", "10.0.1.1", 0x01, 100),
    ("2.2.2.2", "10.0.1.2", 0x02, 50),
    ("3.3.3.3", "10.0.1.3", 0x03, 10),
    ("5.5.5.5", "10.0.1.5", 0x05, 5),
]):
    ospf = build_ospf_hello(rid, "0.0.0.0", "255.255.255.0",
                            10, 40, prio, "1.1.1.1", "2.2.2.2",
                            nbr_sets[rid])
    pkts.append((BASE_T + 10 + i * 0.5, build_frame(mac, ip, ALLSPF, ospf)))

write_pcap("/data/captures/broadcast_network.pcap", pkts)

# ================================================================
# Scenario 3 — Timing violation: gap > DeadInterval (40 s)
# R3 <-> R4 P2P
# ================================================================
pkts = []

# T+0  R3 Hello
ospf = build_ospf_hello("3.3.3.3", "0.0.0.0", "255.255.255.252",
                        10, 40, 1, "0.0.0.0", "0.0.0.0", [])
pkts.append((BASE_T, build_frame(0x03, "10.0.2.1", ALLSPF, ospf)))

# T+1  R4 Hello (no nbrs)
ospf = build_ospf_hello("4.4.4.4", "0.0.0.0", "255.255.255.252",
                        10, 40, 1, "0.0.0.0", "0.0.0.0", [])
pkts.append((BASE_T + 1, build_frame(0x04, "10.0.2.2", ALLSPF, ospf)))

# T+10 R3 Hello (lists R4)
ospf = build_ospf_hello("3.3.3.3", "0.0.0.0", "255.255.255.252",
                        10, 40, 1, "0.0.0.0", "0.0.0.0", ["4.4.4.4"])
pkts.append((BASE_T + 10, build_frame(0x03, "10.0.2.1", ALLSPF, ospf)))

# T+11 R4 Hello (lists R3) — adjacency starts
ospf = build_ospf_hello("4.4.4.4", "0.0.0.0", "255.255.255.252",
                        10, 40, 1, "0.0.0.0", "0.0.0.0", ["3.3.3.3"])
pkts.append((BASE_T + 11, build_frame(0x04, "10.0.2.2", ALLSPF, ospf)))

# T+55 R4 Hello (lists R3) — gap = 44 s > 40 s DeadInterval
ospf = build_ospf_hello("4.4.4.4", "0.0.0.0", "255.255.255.252",
                        10, 40, 1, "0.0.0.0", "0.0.0.0", ["3.3.3.3"])
pkts.append((BASE_T + 55, build_frame(0x04, "10.0.2.2", ALLSPF, ospf)))

write_pcap("/data/captures/timing_violation.pcap", pkts)

# ================================================================
# Scenario 4 — HelloInterval parameter mismatch
# R3 uses HelloInterval=10 / DeadInterval=40
# R4 uses HelloInterval=20 / DeadInterval=80  (VIOLATION)
# ================================================================
pkts = []

# T+0  R3 Hello (HI=10, DI=40)
ospf = build_ospf_hello("3.3.3.3", "0.0.0.0", "255.255.255.252",
                        10, 40, 1, "0.0.0.0", "0.0.0.0", [])
pkts.append((BASE_T, build_frame(0x03, "10.0.2.1", ALLSPF, ospf)))

# T+1  R4 Hello (HI=20, DI=80) — mismatch!
ospf = build_ospf_hello("4.4.4.4", "0.0.0.0", "255.255.255.252",
                        20, 80, 1, "0.0.0.0", "0.0.0.0", [])
pkts.append((BASE_T + 1, build_frame(0x04, "10.0.2.2", ALLSPF, ospf)))

# T+10 R3 Hello (HI=10, lists R4)
ospf = build_ospf_hello("3.3.3.3", "0.0.0.0", "255.255.255.252",
                        10, 40, 1, "0.0.0.0", "0.0.0.0", ["4.4.4.4"])
pkts.append((BASE_T + 10, build_frame(0x03, "10.0.2.1", ALLSPF, ospf)))

# T+21 R4 Hello (HI=20, lists R3) — still mismatched
ospf = build_ospf_hello("4.4.4.4", "0.0.0.0", "255.255.255.252",
                        20, 80, 1, "0.0.0.0", "0.0.0.0", ["3.3.3.3"])
pkts.append((BASE_T + 21, build_frame(0x04, "10.0.2.2", ALLSPF, ospf)))

write_pcap("/data/captures/param_mismatch.pcap", pkts)

print("Generated 4 pcap files in /data/captures/")
