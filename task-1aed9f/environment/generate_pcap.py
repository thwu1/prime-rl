#!/usr/bin/env python3
"""Generate a PCAP file with BGP UPDATE messages for the route analysis task.

Creates valid Ethernet/IPv4/TCP/BGP packets that tshark can dissect.
Each packet contains a BGP UPDATE advertising a prefix with path attributes.
"""
import struct
import socket
import os


def ip_checksum(data):
    """Calculate IP header checksum (RFC 1071)."""
    if len(data) % 2:
        data = data + b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i + 1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF


def make_bgp_origin(value):
    """ORIGIN path attribute. 0=IGP, 1=EGP, 2=INCOMPLETE."""
    return struct.pack('!BBB', 0x40, 1, 1) + struct.pack('!B', value)


def make_bgp_as_path(segments):
    """AS_PATH path attribute. segments = [(seg_type, [asn, ...]), ...]
    seg_type: 1=AS_SET, 2=AS_SEQUENCE, 3=AS_CONFED_SEQUENCE, 4=AS_CONFED_SET
    Uses 2-byte ASNs.
    """
    path_data = bytearray()
    for seg_type, asns in segments:
        path_data.append(seg_type)
        path_data.append(len(asns))
        for asn in asns:
            path_data.extend(struct.pack('!H', asn))
    return struct.pack('!BBB', 0x40, 2, len(path_data)) + bytes(path_data)


def make_bgp_next_hop(ip_str):
    """NEXT_HOP path attribute."""
    return struct.pack('!BBB', 0x40, 3, 4) + socket.inet_aton(ip_str)


def make_bgp_med(value):
    """MULTI_EXIT_DISC (MED) path attribute."""
    return struct.pack('!BBB', 0x80, 4, 4) + struct.pack('!I', value)


def make_bgp_update(origin, as_path_segments, next_hop, med, nlri_prefix, nlri_len):
    """Construct a complete BGP UPDATE message."""
    attrs = bytearray()
    attrs.extend(make_bgp_origin(origin))
    attrs.extend(make_bgp_as_path(as_path_segments))
    attrs.extend(make_bgp_next_hop(next_hop))
    if med is not None:
        attrs.extend(make_bgp_med(med))

    nlri = bytearray()
    nlri.append(nlri_len)
    prefix_bytes = (nlri_len + 7) // 8
    ip_bytes = socket.inet_aton(nlri_prefix)
    nlri.extend(ip_bytes[:prefix_bytes])

    body = struct.pack('!H', 0)                    # withdrawn routes length
    body += struct.pack('!H', len(attrs))           # total path attribute length
    body += bytes(attrs)
    body += bytes(nlri)

    marker = b'\xff' * 16
    msg_len = 19 + len(body)
    header = marker + struct.pack('!HB', msg_len, 2)

    return header + body


def make_packet(src_ip, dst_ip, src_port, dst_port, payload, seq_num):
    """Wrap BGP payload in TCP/IP/Ethernet headers."""
    tcp_header = struct.pack('!HHIIBBHHH',
                             src_port, dst_port,
                             seq_num, 0,
                             (5 << 4), 0x18,
                             65535, 0, 0)

    total_length = 20 + 20 + len(payload)
    ip_header = struct.pack('!BBHHHBBH4s4s',
                            0x45, 0x00,
                            total_length, 0x1234,
                            0x4000, 64, 6, 0,
                            socket.inet_aton(src_ip),
                            socket.inet_aton(dst_ip))
    cksum = ip_checksum(ip_header)
    ip_header = ip_header[:10] + struct.pack('!H', cksum) + ip_header[12:]

    eth_header = (b'\x00\x11\x22\x33\x44\x55'
                  b'\x66\x77\x88\x99\xaa\xbb'
                  + struct.pack('!H', 0x0800))

    return eth_header + ip_header + tcp_header + payload


def write_pcap(filename, packets):
    """Write packets to a PCAP file (little-endian, LINKTYPE_ETHERNET)."""
    os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
    with open(filename, 'wb') as f:
        f.write(struct.pack('<IHHiIII',
                            0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))

        for i, pkt_data in enumerate(packets):
            ts_sec = 1700000000 + i * 10
            f.write(struct.pack('<IIII',
                                ts_sec, 0, len(pkt_data), len(pkt_data)))
            f.write(pkt_data)


def main():
    local_router = '10.0.0.1'

    route_specs = [
        # Packet 0 — Peer 10.0.1.1: AS_SEQUENCE [100], ORIGIN IGP, MED 200
        {
            'src_ip': '10.0.1.1',
            'as_path': [(2, [100])],
            'origin': 0,
            'med': 200,
            'next_hop': '10.0.1.1',
            'nlri_prefix': '10.11.0.0',
            'nlri_len': 24,
        },
        # Packet 1 — Peer 10.0.1.2: AS_SEQUENCE [200], ORIGIN IGP, MED 50
        {
            'src_ip': '10.0.1.2',
            'as_path': [(2, [200])],
            'origin': 0,
            'med': 50,
            'next_hop': '10.0.1.2',
            'nlri_prefix': '10.11.0.0',
            'nlri_len': 24,
        },
        # Packet 2 — Peer 10.0.1.3: AS_SEQUENCE [100], ORIGIN IGP, MED 75
        {
            'src_ip': '10.0.1.3',
            'as_path': [(2, [100])],
            'origin': 0,
            'med': 75,
            'next_hop': '10.0.1.3',
            'nlri_prefix': '10.11.0.0',
            'nlri_len': 24,
        },
        # Packet 3 — Distractor: Peer 10.0.1.4 for prefix 10.12.0.0/24
        {
            'src_ip': '10.0.1.4',
            'as_path': [(2, [500, 600])],
            'origin': 2,
            'med': 300,
            'next_hop': '10.0.1.4',
            'nlri_prefix': '10.12.0.0',
            'nlri_len': 24,
        },
    ]

    packets = []
    for i, spec in enumerate(route_specs):
        bgp_msg = make_bgp_update(
            spec['origin'], spec['as_path'], spec['next_hop'],
            spec['med'], spec['nlri_prefix'], spec['nlri_len'])
        pkt = make_packet(
            spec['src_ip'], local_router,
            50000 + i, 179, bgp_msg, 1000 * (i + 1))
        packets.append(pkt)

    write_pcap('/app/bgp_capture.pcap', packets)
    print(f"Generated PCAP with {len(packets)} BGP UPDATE packets")


if __name__ == '__main__':
    main()
