#!/usr/bin/env python3
"""Generate synthetic pcap capture for TCP host profiling task.

Creates a pcap with traffic from 4 distinct host profiles plus noise:
  - 10.0.0.1: Linux 4.x, direct connection, 5 SYNs with timestamps (250 Hz)
  - 192.168.1.100: Windows 10, 3 hops away, 3 SYNs without timestamps
  - 172.16.0.1: NAT gateway mixing Linux (3 SYNs) + macOS (1 SYN)
  - 10.1.1.1: Linux 4.x, 9 hops away, 3 SYNs with timestamps (250 Hz)
  - Noise: ARP, UDP, TCP ACK, SYN-ACK
"""
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


def build_tcp_options(specs):
    data = b''
    for spec in specs:
        kind = spec[0]
        if kind == 'mss':
            data += struct.pack('!BBH', 2, 4, spec[1])
        elif kind == 'ws':
            data += struct.pack('!BBB', 3, 3, spec[1])
        elif kind == 'sok':
            data += struct.pack('!BB', 4, 2)
        elif kind == 'ts':
            data += struct.pack('!BBII', 8, 10, spec[1], spec[2])
        elif kind == 'nop':
            data += struct.pack('!B', 1)
        elif kind == 'eol':
            pad = spec[1] if len(spec) > 1 else 0
            data += b'\x00' + b'\x00' * pad
    return data


def build_syn_packet(src_ip, dst_ip, src_port, dst_port,
                     ttl, window, ip_id, tos, tcp_option_specs,
                     seq=1000, df=True, urg_ptr=0, psh=False,
                     ack=False, ack_seq=0):
    opts = build_tcp_options(tcp_option_specs)
    while len(opts) % 4 != 0:
        opts += b'\x00'

    tcp_hdr_len = 20 + len(opts)
    data_offset = tcp_hdr_len // 4

    flags = 0x002  # SYN
    if ack:
        flags |= 0x010
    if psh:
        flags |= 0x008
    doff_flags = (data_offset << 12) | flags

    tcp_header = struct.pack('!HHIIHHHH',
                             src_port, dst_port, seq, ack_seq,
                             doff_flags, window, 0, urg_ptr)
    tcp_full = tcp_header + opts

    ip_hdr_len = 20
    total_len = ip_hdr_len + len(tcp_full)
    flags_frag = 0x4000 if df else 0

    ip_header = struct.pack('!BBHHHBBH4s4s',
                            0x45, tos, total_len, ip_id,
                            flags_frag, ttl, 6, 0,
                            socket.inet_aton(src_ip),
                            socket.inet_aton(dst_ip))
    chk = ip_checksum(ip_header)
    ip_header = ip_header[:10] + struct.pack('!H', chk) + ip_header[12:]

    eth = b'\xff\xff\xff\xff\xff\xff\x00\x11\x22\x33\x44\x55\x08\x00'
    return eth + ip_header + tcp_full


def build_ack_packet(src_ip, dst_ip, src_port, dst_port):
    doff_flags = (5 << 12) | 0x010  # ACK only
    tcp_header = struct.pack('!HHIIHHHH',
                             src_port, dst_port, 2000, 1001,
                             doff_flags, 14600, 0, 0)
    total_len = 20 + len(tcp_header)
    ip_header = struct.pack('!BBHHHBBH4s4s',
                            0x45, 0, total_len, 0,
                            0x4000, 64, 6, 0,
                            socket.inet_aton(src_ip),
                            socket.inet_aton(dst_ip))
    chk = ip_checksum(ip_header)
    ip_header = ip_header[:10] + struct.pack('!H', chk) + ip_header[12:]
    eth = b'\xff\xff\xff\xff\xff\xff\x00\x11\x22\x33\x44\x55\x08\x00'
    return eth + ip_header + tcp_header


def build_arp_packet():
    eth = b'\xff\xff\xff\xff\xff\xff\x00\x11\x22\x33\x44\x55\x08\x06'
    arp = struct.pack('!HHBBH', 1, 0x0800, 6, 4, 1)
    arp += b'\x00\x11\x22\x33\x44\x55' + socket.inet_aton('10.0.0.1')
    arp += b'\x00\x00\x00\x00\x00\x00' + socket.inet_aton('10.0.0.2')
    return eth + arp


def build_udp_packet():
    udp_payload = struct.pack('!HHHH', 53, 1234, 12, 0) + b'\x00\x00\x00\x00'
    total_len = 20 + len(udp_payload)
    ip_header = struct.pack('!BBHHHBBH4s4s',
                            0x45, 0, total_len, 0,
                            0x4000, 64, 17, 0,
                            socket.inet_aton('10.0.0.1'),
                            socket.inet_aton('10.0.0.2'))
    chk = ip_checksum(ip_header)
    ip_header = ip_header[:10] + struct.pack('!H', chk) + ip_header[12:]
    eth = b'\xff\xff\xff\xff\xff\xff\x00\x11\x22\x33\x44\x55\x08\x00'
    return eth + ip_header + udp_payload


def write_pcap(filepath, packets_with_times):
    with open(filepath, 'wb') as f:
        f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for ts, pkt in packets_with_times:
            ts_sec = int(ts)
            ts_usec = int((ts - ts_sec) * 1000000)
            f.write(struct.pack('<IIII', ts_sec, ts_usec, len(pkt), len(pkt)))
            f.write(pkt)


def generate():
    packets = []

    # --- Host A: Linux 4.x, direct connection (TTL=64), 5 SYN packets ---
    # TCP timestamp frequency = 250 Hz, uptime = 1000000/250 = 4000 sec
    linux_opts = lambda tsval: [
        ('mss', 1460), ('sok',), ('ts', tsval, 0), ('nop',), ('ws', 7)
    ]
    for i, (port, tsval) in enumerate([
        (80, 1000000), (443, 1000250), (8080, 1000500),
        (8443, 1000750), (22, 1001000)
    ]):
        packets.append((
            1000000.0 + i,
            build_syn_packet('10.0.0.1', '10.0.0.2', 40000 + i, port,
                             ttl=64, window=14600, ip_id=0x1234 + i, tos=0,
                             tcp_option_specs=linux_opts(tsval))
        ))

    # --- Host B: Windows 10, 3 hops away (TTL=125), no timestamps ---
    win_opts = [('mss', 1460), ('nop',), ('ws', 8), ('nop',), ('nop',), ('sok',)]
    for i, port in enumerate([80, 443, 8080]):
        packets.append((
            1000005.0 + i * 2,
            build_syn_packet('192.168.1.100', '10.0.0.2', 50000 + i, port,
                             ttl=125, window=8192, ip_id=0x5678 + i, tos=0,
                             tcp_option_specs=win_opts)
        ))

    # --- Host C: NAT gateway (3 Linux SYNs + 1 macOS SYN from same IP) ---
    for i, tsval in enumerate([2000000, 2000250, 2000500]):
        packets.append((
            1000010.0 + i,
            build_syn_packet('172.16.0.1', '10.0.0.2', 55000 + i, 80,
                             ttl=64, window=14600, ip_id=0x1111 * (i + 1),
                             tos=0, tcp_option_specs=linux_opts(tsval))
        ))
    macos_opts = [
        ('mss', 1460), ('nop',), ('ws', 6), ('nop',), ('nop',),
        ('ts', 800000, 0), ('sok',), ('eol', 1)
    ]
    packets.append((
        1000013.0,
        build_syn_packet('172.16.0.1', '10.0.0.2', 55003, 443,
                         ttl=64, window=65535, ip_id=0, tos=0,
                         tcp_option_specs=macos_opts)
    ))

    # --- Host D: Linux 4.x, 9 hops away (TTL=55), MSS=1400 ---
    # Frequency 250 Hz, uptime = 3000000/250 = 12000 sec
    linux_opts_1400 = lambda tsval: [
        ('mss', 1400), ('sok',), ('ts', tsval, 0), ('nop',), ('ws', 7)
    ]
    for i, tsval in enumerate([3000000, 3000500, 3001000]):
        packets.append((
            1000015.0 + i * 2,
            build_syn_packet('10.1.1.1', '10.0.0.2', 45000 + i, 80 + i,
                             ttl=55, window=14000, ip_id=0xabcd + i, tos=0,
                             tcp_option_specs=linux_opts_1400(tsval))
        ))

    # --- Noise traffic (must be filtered) ---
    packets.append((1000020.0, build_arp_packet()))
    packets.append((1000021.0, build_udp_packet()))
    packets.append((1000022.0, build_ack_packet('10.0.0.2', '10.0.0.1', 80, 40000)))
    packets.append((
        1000023.0,
        build_syn_packet('10.0.0.2', '10.0.0.1', 80, 40000,
                         ttl=64, window=14480, ip_id=0, tos=0,
                         tcp_option_specs=[('mss', 1460), ('sok',),
                                           ('ts', 1000, 500), ('nop',), ('ws', 7)],
                         ack=True, ack_seq=1001)
    ))

    packets.sort(key=lambda x: x[0])
    write_pcap('/app/capture.pcap', packets)


if __name__ == '__main__':
    generate()
