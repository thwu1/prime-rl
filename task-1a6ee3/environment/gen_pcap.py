#!/usr/bin/env python3
"""Generate PCAP file with crafted TCP SYN packets for OS fingerprinting task."""
import struct
import socket
import os


def ip_checksum(data):
    """Compute standard Internet checksum (RFC 1071)."""
    if len(data) % 2:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) | data[i + 1]
    while s >> 16:
        s = (s >> 16) + (s & 0xffff)
    return (~s) & 0xffff


def tcp_checksum(src_ip, dst_ip, tcp_data):
    """Compute TCP checksum using pseudo-header."""
    pseudo = struct.pack('!4s4sBBH',
                         socket.inet_aton(src_ip),
                         socket.inet_aton(dst_ip),
                         0, 6, len(tcp_data))
    return ip_checksum(pseudo + tcp_data)


def make_tcp_options(opt_list):
    """Build TCP options bytes from a specification list.

    Each element is (kind, data) where kind is one of:
        'mss'  -> data = int (MSS value)
        'nop'  -> data = None
        'ws'   -> data = int (window scale shift count)
        'sok'  -> data = None (SACK OK)
        'ts'   -> data = (ts_val, ts_ecr) tuple
        'eol'  -> data = None
    Returns bytes padded to 4-byte boundary.
    """
    result = b''
    for kind, data in opt_list:
        if kind == 'mss':
            result += struct.pack('!BBH', 2, 4, data)
        elif kind == 'nop':
            result += b'\x01'
        elif kind == 'ws':
            result += struct.pack('!BBB', 3, 3, data)
        elif kind == 'sok':
            result += struct.pack('!BB', 4, 2)
        elif kind == 'ts':
            ts_val, ts_ecr = data
            result += struct.pack('!BBII', 8, 10, ts_val, ts_ecr)
        elif kind == 'eol':
            result += b'\x00'
    # Pad to 4-byte boundary with zeros
    while len(result) % 4:
        result += b'\x00'
    return result


def make_packet(src_mac, dst_mac, src_ip, dst_ip, src_port, dst_port,
                ttl, tos, ip_id, ip_flags_frag, seq, tcp_flags, window,
                urg_ptr, tcp_options_list, ack_seq=0):
    """Build a complete Ethernet + IPv4 + TCP packet with correct checksums."""
    # Build TCP options
    tcp_opts = make_tcp_options(tcp_options_list)

    # Build TCP header
    data_offset = (20 + len(tcp_opts)) // 4
    tcp_flags_field = (data_offset << 12) | tcp_flags
    tcp_header = struct.pack('!HHIIHHHH',
                             src_port, dst_port,
                             seq, ack_seq,
                             tcp_flags_field, window,
                             0,  # checksum placeholder
                             urg_ptr)
    tcp_header += tcp_opts

    # Compute and insert TCP checksum
    tcp_cksum = tcp_checksum(src_ip, dst_ip, tcp_header)
    tcp_header = tcp_header[:16] + struct.pack('!H', tcp_cksum) + tcp_header[18:]

    # Build IPv4 header
    ip_total_len = 20 + len(tcp_header)
    ip_header = struct.pack('!BBHHHBBH4s4s',
                            0x45, tos, ip_total_len,
                            ip_id, ip_flags_frag,
                            ttl, 6, 0,  # checksum placeholder
                            socket.inet_aton(src_ip),
                            socket.inet_aton(dst_ip))

    # Compute and insert IP checksum
    ip_cksum = ip_checksum(ip_header)
    ip_header = ip_header[:10] + struct.pack('!H', ip_cksum) + ip_header[12:]

    # Build Ethernet header
    eth_header = (bytes.fromhex(dst_mac.replace(':', '')) +
                  bytes.fromhex(src_mac.replace(':', '')) +
                  struct.pack('!H', 0x0800))

    return eth_header + ip_header + tcp_header


def write_pcap(filename, packets):
    """Write packets to a PCAP file (little-endian, Ethernet link type)."""
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'wb') as f:
        # Global header
        f.write(struct.pack('<IHHiIII',
                            0xa1b2c3d4,  # magic (little-endian)
                            2, 4,        # version 2.4
                            0,           # timezone offset
                            0,           # timestamp accuracy
                            65535,       # snaplen
                            1))          # link type: Ethernet

        for i, pkt in enumerate(packets):
            ts_sec = 1700000000 + i
            ts_usec = 0
            f.write(struct.pack('<IIII',
                                ts_sec, ts_usec,
                                len(pkt), len(pkt)))
            f.write(pkt)


def main():
    dst_ip = '192.168.1.1'
    dst_mac = '02:00:00:00:00:01'

    packets = []

    # Packet 0: Linux 5.x
    # TTL=62 (guess 64), DF set, ID non-zero, MSS=1460, Win=29200=mss*20, WS=7
    # Options: mss,sok,ts,nop,ws
    packets.append(make_packet(
        src_mac='0a:00:01:0a:00:01', dst_mac=dst_mac,
        src_ip='10.0.1.10', dst_ip=dst_ip,
        src_port=49152, dst_port=80,
        ttl=62, tos=0x00, ip_id=0x4A32, ip_flags_frag=0x4000,
        seq=0x12345678, tcp_flags=0x002, window=29200, urg_ptr=0,
        tcp_options_list=[
            ('mss', 1460), ('sok', None), ('ts', (123456, 0)),
            ('nop', None), ('ws', 7)
        ]
    ))

    # Packet 1: Windows 10
    # TTL=125 (guess 128), DF set, ID non-zero, MSS=1460, Win=8192, WS=8
    # Options: mss,nop,ws,nop,nop,sok
    packets.append(make_packet(
        src_mac='0a:00:02:14:00:02', dst_mac=dst_mac,
        src_ip='10.0.2.20', dst_ip=dst_ip,
        src_port=49200, dst_port=443,
        ttl=125, tos=0x00, ip_id=0xB1F7, ip_flags_frag=0x4000,
        seq=0xAABBCCDD, tcp_flags=0x002, window=8192, urg_ptr=0,
        tcp_options_list=[
            ('mss', 1460), ('nop', None), ('ws', 8),
            ('nop', None), ('nop', None), ('sok', None)
        ]
    ))

    # Packet 2: macOS 12
    # TTL=63 (guess 64), DF set, ID non-zero, MSS=1460, Win=65535, WS=6
    # Options: mss,nop,ws,nop,nop,ts,sok,eol (23 bytes + 1 pad = 24)
    packets.append(make_packet(
        src_mac='0a:00:03:1e:00:03', dst_mac=dst_mac,
        src_ip='10.0.3.30', dst_ip=dst_ip,
        src_port=49300, dst_port=80,
        ttl=63, tos=0x00, ip_id=0xCE84, ip_flags_frag=0x4000,
        seq=0x11223344, tcp_flags=0x002, window=65535, urg_ptr=0,
        tcp_options_list=[
            ('mss', 1460), ('nop', None), ('ws', 6),
            ('nop', None), ('nop', None), ('ts', (98765, 0)),
            ('sok', None), ('eol', None)
        ]
    ))

    # Packet 3: FreeBSD 13
    # TTL=64, DF set, ID=0 (no id+ quirk), MSS=1460, Win=65535, WS=6
    # Options: mss,nop,ws,sok,ts (20 bytes exactly)
    packets.append(make_packet(
        src_mac='0a:00:04:28:00:04', dst_mac=dst_mac,
        src_ip='10.0.4.40', dst_ip=dst_ip,
        src_port=49400, dst_port=443,
        ttl=64, tos=0x00, ip_id=0x0000, ip_flags_frag=0x4000,
        seq=0xDEADBEEF, tcp_flags=0x002, window=65535, urg_ptr=0,
        tcp_options_list=[
            ('mss', 1460), ('nop', None), ('ws', 6),
            ('sok', None), ('ts', (65281, 0))
        ]
    ))

    # Packet 4: Linux 4.x with ECN
    # TTL=62 (guess 64), DF set, ID non-zero, TOS=0x03 (ECN bits), TCP flags=SYN+ECE+CWR
    # Options: mss,sok,ts,nop,ws (same as Linux 5.x)
    packets.append(make_packet(
        src_mac='0a:00:05:32:00:05', dst_mac=dst_mac,
        src_ip='10.0.5.50', dst_ip=dst_ip,
        src_port=49500, dst_port=80,
        ttl=62, tos=0x03, ip_id=0x7D91, ip_flags_frag=0x4000,
        seq=0xFEEDFACE, tcp_flags=0x0C2, window=29200, urg_ptr=0,
        tcp_options_list=[
            ('mss', 1460), ('sok', None), ('ts', (200000, 0)),
            ('nop', None), ('ws', 7)
        ]
    ))

    # Packet 5: Windows Server 2019
    # TTL=126 (guess 128), DF set, ID non-zero, MSS=1460, Win=8192, WS=8
    # Options: mss,nop,ws,sok,ts (20 bytes)
    packets.append(make_packet(
        src_mac='0a:00:06:3c:00:06', dst_mac=dst_mac,
        src_ip='10.0.6.60', dst_ip=dst_ip,
        src_port=49600, dst_port=80,
        ttl=126, tos=0x00, ip_id=0x3E55, ip_flags_frag=0x4000,
        seq=0x87654321, tcp_flags=0x002, window=8192, urg_ptr=0,
        tcp_options_list=[
            ('mss', 1460), ('nop', None), ('ws', 8),
            ('sok', None), ('ts', (172800, 0))
        ]
    ))

    # Packet 6: OpenBSD 7.x
    # TTL=61 (guess 64), DF set, ID=0 (no id+ quirk), MSS=1460, Win=16384, WS=0
    # Options: mss,nop,nop,sok,nop,ws,nop,nop,ts (24 bytes)
    packets.append(make_packet(
        src_mac='0a:00:07:46:00:07', dst_mac=dst_mac,
        src_ip='10.0.7.70', dst_ip=dst_ip,
        src_port=49700, dst_port=443,
        ttl=61, tos=0x00, ip_id=0x0000, ip_flags_frag=0x4000,
        seq=0xC0FFEE00, tcp_flags=0x002, window=16384, urg_ptr=0,
        tcp_options_list=[
            ('mss', 1460), ('nop', None), ('nop', None),
            ('sok', None), ('nop', None), ('ws', 0),
            ('nop', None), ('nop', None), ('ts', (43981, 0))
        ]
    ))

    # Packet 7: Solaris 11
    # TTL=253 (guess 255), NO DF, ID non-zero, MSS=1460, Win=49640=mss*34, WS=0
    # Options: nop,nop,ts,mss,nop,ws,sok,eol (22 bytes + eol + 1 pad = 24)
    packets.append(make_packet(
        src_mac='0a:00:08:50:00:08', dst_mac=dst_mac,
        src_ip='10.0.8.80', dst_ip=dst_ip,
        src_port=49800, dst_port=80,
        ttl=253, tos=0x00, ip_id=0x9ABC, ip_flags_frag=0x0000,
        seq=0xBADC0DE0, tcp_flags=0x002, window=49640, urg_ptr=0,
        tcp_options_list=[
            ('nop', None), ('nop', None), ('ts', (250000, 0)),
            ('mss', 1460), ('nop', None), ('ws', 0),
            ('sok', None), ('eol', None)
        ]
    ))

    # Packet 8: SYN-ACK distractor (should be filtered out)
    # TCP flags = SYN+ACK (0x012), should NOT appear in results
    packets.append(make_packet(
        src_mac='02:00:00:00:00:01', dst_mac='0a:00:01:0a:00:01',
        src_ip='192.168.1.1', dst_ip='10.0.1.10',
        src_port=80, dst_port=49152,
        ttl=64, tos=0x00, ip_id=0x1111, ip_flags_frag=0x4000,
        seq=0xAAAAAAAA, tcp_flags=0x012, window=29200, urg_ptr=0,
        tcp_options_list=[
            ('mss', 1460), ('sok', None), ('ts', (123457, 123456)),
            ('nop', None), ('ws', 7)
        ],
        ack_seq=0x12345679
    ))

    write_pcap('/app/captures/syn_packets.pcap', packets)
    print(f"Generated PCAP with {len(packets)} packets at /app/captures/syn_packets.pcap")


if __name__ == '__main__':
    main()
