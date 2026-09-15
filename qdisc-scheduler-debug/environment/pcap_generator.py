#!/usr/bin/env python3
"""Generate a multi-class network traffic pcap from the SLA spec.

Creates Ethernet/IP/UDP packets with correct DSCP markings and
nanosecond-resolution timestamps in standard pcap format.

"""
import struct
import random
import json
import sys

# Nanosecond-resolution pcap magic number
PCAP_MAGIC_NS = 0xa1b23c4d


def compute_ip_checksum(header_bytes):
    """Compute IP header checksum per RFC 791."""
    if len(header_bytes) % 2:
        header_bytes += b'\x00'
    total = 0
    for i in range(0, len(header_bytes), 2):
        word = (header_bytes[i] << 8) + header_bytes[i + 1]
        total += word
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def make_packet_bytes(flow_id, dscp, size_bytes):
    """Create Ethernet + IP + UDP packet bytes.

    size_bytes = IP total length (what tshark reports as ip.len).
    """
    src_port = 10000 + flow_id
    dst_port = 20000 + flow_id

    udp_payload_len = max(0, size_bytes - 28)  # IP(20) + UDP(8)
    udp_payload = b'\x00' * udp_payload_len

    # UDP header (checksum 0 — optional for UDP/IPv4)
    udp_len = 8 + udp_payload_len
    udp_header = struct.pack('!HHHH', src_port, dst_port, udp_len, 0)

    # IP header with zeroed checksum for computation
    ip_dscp_ecn = (dscp << 2) & 0xFF
    ip_header_no_cksum = struct.pack(
        '!BBHHHBBH4s4s',
        0x45,           # version=4, IHL=5
        ip_dscp_ecn,    # DSCP + ECN
        size_bytes,     # total length
        0, 0x4000,      # identification, flags (DF) + fragment offset
        64, 17, 0,      # TTL, protocol=UDP, checksum placeholder
        b'\x0a\x00\x00\x01',  # src: 10.0.0.1
        b'\x0a\x00\x00\x02',  # dst: 10.0.0.2
    )
    cksum = compute_ip_checksum(ip_header_no_cksum)
    ip_header = struct.pack(
        '!BBHHHBBH4s4s',
        0x45, ip_dscp_ecn, size_bytes,
        0, 0x4000,
        64, 17, cksum,
        b'\x0a\x00\x00\x01',
        b'\x0a\x00\x00\x02',
    )

    # Ethernet header
    eth = (b'\x00\x00\x00\x00\x00\x02'   # dst MAC
           + b'\x00\x00\x00\x00\x00\x01'  # src MAC
           + struct.pack('!H', 0x0800))    # EtherType: IPv4

    return eth + ip_header + udp_header + udp_payload


def generate_packets(spec):
    """Generate packet tuples: (arrival_ns, flow_id, dscp, size_bytes)."""
    duration_sec = spec['duration_sec']
    random.seed(42)
    packets = []

    for tc_class in spec['traffic_classes']:
        dscp = tc_class['dscp']
        for flow_info in tc_class['flows']:
            flow_id = flow_info['flow_id']
            rate_bps = flow_info['rate_bps']
            pkt_size = flow_info['packet_size_bytes']
            pattern = flow_info.get('pattern', 'cbr')

            if pattern == 'cbr':
                interval_ns = int(pkt_size * 8 / rate_bps * 1e9)
                t = random.randint(0, interval_ns // 2)
                while t < duration_sec * 1e9:
                    packets.append((int(t), flow_id, dscp, pkt_size))
                    jitter = random.randint(-interval_ns // 20,
                                            interval_ns // 20)
                    t += interval_ns + jitter

            elif pattern == 'bursty':
                burst_size = flow_info.get('burst_packets', 12)
                accel = 3
                fast_interval_ns = int(pkt_size * 8
                                       / (rate_bps * accel) * 1e9)
                burst_duration_ns = fast_interval_ns * burst_size
                pause_ns = burst_duration_ns * (accel - 1)
                t = random.randint(0, pause_ns // 2)
                while t < duration_sec * 1e9:
                    for _ in range(burst_size):
                        if t >= duration_sec * 1e9:
                            break
                        actual_size = pkt_size + random.randint(-50, 50)
                        packets.append((int(t), flow_id, dscp, actual_size))
                        jitter = random.randint(-fast_interval_ns // 20,
                                                fast_interval_ns // 20)
                        t += fast_interval_ns + jitter
                    jitter = random.randint(-pause_ns // 10, pause_ns // 10)
                    t += pause_ns + jitter

            elif pattern == 'bulk':
                interval_ns = int(pkt_size * 8 / rate_bps * 1e9)
                t = random.randint(0, interval_ns)
                while t < duration_sec * 1e9:
                    actual_size = pkt_size + random.randint(-100, 100)
                    actual_size = max(64, actual_size)
                    packets.append((int(t), flow_id, dscp, actual_size))
                    jitter = random.randint(-interval_ns // 10,
                                            interval_ns // 10)
                    t += interval_ns + jitter

    packets.sort(key=lambda p: (p[0], p[1]))
    return packets


def write_pcap(filename, packets):
    """Write packets to a nanosecond-resolution pcap file."""
    with open(filename, 'wb') as f:
        # Global header: native byte order, nanosecond resolution
        f.write(struct.pack('=IHHiIII',
                            PCAP_MAGIC_NS, 2, 4, 0, 0, 65535, 1))

        for arrival_ns, flow_id, dscp, size_bytes in packets:
            pkt_data = make_packet_bytes(flow_id, dscp, size_bytes)
            ts_sec = arrival_ns // 1_000_000_000
            ts_nsec = arrival_ns % 1_000_000_000
            f.write(struct.pack('=IIII',
                                ts_sec, ts_nsec,
                                len(pkt_data), len(pkt_data)))
            f.write(pkt_data)


def main():
    spec_path = sys.argv[1] if len(sys.argv) > 1 else '/app/sla_spec.json'
    output_path = sys.argv[2] if len(sys.argv) > 2 else '/app/capture.pcap'

    with open(spec_path) as f:
        spec = json.load(f)

    packets = generate_packets(spec)
    write_pcap(output_path, packets)

    n_flows = len(set(p[1] for p in packets))
    print(f"Generated pcap with {len(packets)} packets across {n_flows} flows")


if __name__ == '__main__':
    main()
