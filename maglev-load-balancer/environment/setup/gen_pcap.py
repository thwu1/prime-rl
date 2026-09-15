#!/usr/bin/env python3
"""
Generate incident.pcap for the L4 load balancer forensics task.

Creates a PCAP file with UDP traffic showing uneven backend distribution,
simulating the incident described in incident.md.

"""

import os
import random
import struct
import socket

random.seed(42)

# --- Configuration ---
VIP = '10.0.0.100'
BACKENDS = ['10.0.0.1', '10.0.0.2', '10.0.0.3', '10.0.0.4']
# Broken distribution weights (backend 3 gets ~45%)
WEIGHTS = [0.12, 0.13, 0.45, 0.30]
NUM_CLIENTS = 200
NUM_REQUESTS = 2500

# Generate deterministic client IPs
CLIENTS = [f'192.168.{i // 256}.{i % 256}' for i in range(1, NUM_CLIENTS + 1)]


def ip_checksum(header_bytes):
    """Compute IP header checksum (RFC 1071)."""
    if len(header_bytes) % 2:
        header_bytes += b'\x00'
    total = 0
    for i in range(0, len(header_bytes), 2):
        total += (header_bytes[i] << 8) + header_bytes[i + 1]
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return ~total & 0xFFFF


def make_packet(src_ip, dst_ip, src_port, dst_port, payload):
    """Build raw Ethernet + IPv4 + UDP packet bytes."""
    # Ethernet header (14 bytes)
    eth = struct.pack('!6s6sH',
                      b'\x00\x11\x22\x33\x44\x55',   # dst MAC
                      b'\xaa\xbb\xcc\xdd\xee\xff',   # src MAC
                      0x0800)                          # EtherType IPv4

    # IP header (20 bytes, checksum placeholder = 0)
    udp_len = 8 + len(payload)
    ip_total = 20 + udp_len
    ip_hdr = struct.pack('!BBHHHBBH4s4s',
                         0x45, 0, ip_total,
                         0, 0x4000,
                         64, 17, 0,
                         socket.inet_aton(src_ip),
                         socket.inet_aton(dst_ip))
    # Insert checksum
    cs = ip_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack('!H', cs) + ip_hdr[12:]

    # UDP header (8 bytes, checksum = 0 = optional for IPv4 UDP)
    udp_hdr = struct.pack('!HHHH', src_port, dst_port, udp_len, 0)

    return eth + ip_hdr + udp_hdr + payload


def write_pcap(filename, packets):
    """Write packets list to a pcap file (libpcap format)."""
    global_hdr = struct.pack('<IHHiIII',
                             0xa1b2c3d4,   # magic
                             2, 4,          # version
                             0, 0,          # tz offset, sigfigs
                             65535,         # snaplen
                             1)             # link type: Ethernet

    base_ts = 1738328400  # 2025-01-31 14:00:00 UTC (approx)

    with open(filename, 'wb') as f:
        f.write(global_hdr)
        for idx, pkt in enumerate(packets):
            ts_sec = base_ts + idx // 200
            ts_usec = (idx % 200) * 5000
            rec_hdr = struct.pack('<IIII', ts_sec, ts_usec, len(pkt), len(pkt))
            f.write(rec_hdr)
            f.write(pkt)


def main():
    packets = []

    for _ in range(NUM_REQUESTS):
        client = random.choice(CLIENTS)
        sport = random.randint(1024, 65535)

        # Request: client -> VIP:80
        req = make_packet(client, VIP, sport, 80, b'REQ')
        packets.append(req)

        # Select backend (skewed distribution)
        r = random.random()
        cumul = 0.0
        backend = BACKENDS[-1]
        for j, b in enumerate(BACKENDS):
            cumul += WEIGHTS[j]
            if r < cumul:
                backend = b
                break

        # Response: backend:80 -> client
        resp = make_packet(backend, client, 80, sport, b'RESP')
        packets.append(resp)

    # Write PCAP only -- no ground truth file
    os.makedirs('/app/captures', exist_ok=True)
    write_pcap('/app/captures/incident.pcap', packets)

    print(f'Generated {len(packets)} packets ({NUM_REQUESTS} req/resp pairs)')


if __name__ == '__main__':
    main()
