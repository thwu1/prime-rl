#!/usr/bin/env python3
"""
Generate synthetic network traffic capture (pcap) for forensics task.
Produces deterministic output with fixed seed for reproducible analysis.
"""

import struct
import os


def ip_to_bytes(ip_str):
    return bytes(int(x) for x in ip_str.split('.'))


def compute_checksum(data):
    if len(data) % 2:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i + 1]
    while s >> 16:
        s = (s & 0xffff) + (s >> 16)
    return ~s & 0xffff


# Ethernet header: dst_mac + src_mac + ethertype(IPv4)
ETH_HDR = (b'\x00\x11\x22\x33\x44\x55'
           + b'\x66\x77\x88\x99\xaa\xbb'
           + b'\x08\x00')

SYN = 0x02
SYN_ACK = 0x12
ACK = 0x10
FIN_ACK = 0x11

SERVER = '10.1.0.1'
BASE_TS = 1700000000


class LCG:
    """Simple deterministic PRNG."""
    def __init__(self, seed=42):
        self.state = seed

    def next(self):
        self.state = (self.state * 1103515245 + 12345) & 0x7fffffff
        return self.state


def make_tcp_packet(src_ip, dst_ip, src_port, dst_port, seq, ack_num, flags):
    ip_src = ip_to_bytes(src_ip)
    ip_dst = ip_to_bytes(dst_ip)
    ip_total_len = 40  # 20 IP + 20 TCP

    ip_hdr = struct.pack('>BBHHHBBH',
                         0x45, 0, ip_total_len, 0, 0x4000, 64, 6, 0)
    ip_hdr += ip_src + ip_dst
    ip_cs = compute_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack('>H', ip_cs) + ip_hdr[12:]

    tcp_hdr = struct.pack('>HHIIBBHHH',
                          src_port, dst_port, seq, ack_num,
                          0x50, flags, 65535, 0, 0)
    pseudo = ip_src + ip_dst + struct.pack('>BBH', 0, 6, 20)
    tcp_cs = compute_checksum(pseudo + tcp_hdr)
    tcp_hdr = tcp_hdr[:16] + struct.pack('>H', tcp_cs) + tcp_hdr[18:]

    return ETH_HDR + ip_hdr + tcp_hdr


def make_udp_packet(src_ip, dst_ip, src_port, dst_port, payload):
    ip_src = ip_to_bytes(src_ip)
    ip_dst = ip_to_bytes(dst_ip)
    udp_len = 8 + len(payload)
    ip_total_len = 20 + udp_len

    ip_hdr = struct.pack('>BBHHHBBH',
                         0x45, 0, ip_total_len, 0, 0x4000, 64, 17, 0)
    ip_hdr += ip_src + ip_dst
    ip_cs = compute_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack('>H', ip_cs) + ip_hdr[12:]

    udp_hdr = struct.pack('>HHHH', src_port, dst_port, udp_len, 0)

    return ETH_HDR + ip_hdr + udp_hdr + payload


def generate():
    rng = LCG(42)
    packets = []

    # === SYN flood from 3 attack /24 subnets ===
    # 100 source hosts per /24, 15 SYN-only packets each = 4500 total
    attack_subnets = ['192.0.2', '198.51.100', '203.0.113']
    for subnet in attack_subnets:
        for host in range(1, 101):
            src_ip = '{}.{}'.format(subnet, host)
            for _ in range(15):
                ts_sec = BASE_TS + rng.next() % 100
                ts_usec = rng.next() % 1000000
                src_port = 1024 + rng.next() % 64512
                seq = rng.next()
                pkt = make_tcp_packet(src_ip, SERVER, src_port, 8080,
                                      seq, 0, SYN)
                packets.append((ts_sec, ts_usec, pkt))

    # === Legitimate TCP from 10.0.1.0/24 (10 hosts) ===
    for host in range(1, 11):
        src_ip = '10.0.1.{}'.format(host)
        base_port = 32768 + host * 100

        # 50 SYN per host = 500 total legitimate SYN-only
        for i in range(50):
            ts_sec = BASE_TS + rng.next() % 100
            ts_usec = rng.next() % 1000000
            seq = rng.next()
            pkt = make_tcp_packet(src_ip, SERVER, base_port + i, 8080,
                                  seq, 0, SYN)
            packets.append((ts_sec, ts_usec, pkt))

        # 40 SYN-ACK from server per host = 400 total
        for i in range(40):
            ts_sec = BASE_TS + rng.next() % 100
            ts_usec = rng.next() % 1000000
            seq = rng.next()
            ack = rng.next()
            pkt = make_tcp_packet(SERVER, src_ip, 8080, base_port + i,
                                  seq, ack, SYN_ACK)
            packets.append((ts_sec, ts_usec, pkt))

        # 80 ACK per host = 800 total
        for i in range(80):
            ts_sec = BASE_TS + rng.next() % 100
            ts_usec = rng.next() % 1000000
            seq = rng.next()
            ack = rng.next()
            pkt = make_tcp_packet(src_ip, SERVER, base_port + (i % 40),
                                  8080, seq, ack, ACK)
            packets.append((ts_sec, ts_usec, pkt))

        # 15 FIN-ACK per host = 150 total
        for i in range(15):
            ts_sec = BASE_TS + rng.next() % 100
            ts_usec = rng.next() % 1000000
            seq = rng.next()
            ack = rng.next()
            pkt = make_tcp_packet(src_ip, SERVER, base_port + i, 8080,
                                  seq, ack, FIN_ACK)
            packets.append((ts_sec, ts_usec, pkt))

    # === UDP DNS reflection (src port 53) ===
    # 18 unique source IPs, 12 packets each = 216 total
    for src_host in range(1, 19):
        src_ip = '172.16.0.{}'.format(src_host)
        for _ in range(12):
            ts_sec = BASE_TS + rng.next() % 100
            ts_usec = rng.next() % 1000000
            dst_port = 32768 + rng.next() % 32768
            payload = b'\x00' * 64
            pkt = make_udp_packet(src_ip, SERVER, 53, dst_port, payload)
            packets.append((ts_sec, ts_usec, pkt))

    # Sort packets chronologically
    packets.sort(key=lambda x: (x[0], x[1]))

    os.makedirs('/app/data', exist_ok=True)
    with open('/app/data/traffic_capture.pcap', 'wb') as f:
        # PCAP global header (little-endian)
        f.write(struct.pack('<IHHiIII',
                            0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for ts_sec, ts_usec, pkt in packets:
            f.write(struct.pack('<IIII',
                                ts_sec, ts_usec, len(pkt), len(pkt)))
            f.write(pkt)

    print("Generated {} packets -> /app/data/traffic_capture.pcap".format(
        len(packets)))


if __name__ == '__main__':
    generate()
