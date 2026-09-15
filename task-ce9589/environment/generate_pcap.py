#!/usr/bin/env python3
"""Generate pcap file with DNS traffic for services.lab domain (plus noise)."""

import struct
import socket
import ipaddress
import os

TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28


def encode_name(name):
    result = b''
    for label in name.rstrip('.').split('.'):
        if label:
            result += bytes([len(label)]) + label.encode()
    return result + b'\x00'


def ip_checksum(data):
    if len(data) % 2:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i + 1]
    while s >> 16:
        s = (s >> 16) + (s & 0xFFFF)
    return (~s) & 0xFFFF


def make_dns_query(qid, qname, qtype):
    flags = 0x0100
    header = struct.pack('!HHHHHH', qid, flags, 1, 0, 0, 0)
    question = encode_name(qname) + struct.pack('!HH', qtype, 1)
    return header + question


def make_dns_response(qid, qname, qtype, answers, rcode=0, aa=True):
    flags = 0x8000
    if aa:
        flags |= 0x0400
    flags |= (rcode & 0xF)
    header = struct.pack('!HHHHHH', qid, flags, 1, len(answers), 0, 0)
    question = encode_name(qname) + struct.pack('!HH', qtype, 1)
    answer_data = b''
    for name, rtype, ttl, rdata in answers:
        answer_data += encode_name(name)
        answer_data += struct.pack('!HHIH', rtype, 1, ttl, len(rdata))
        answer_data += rdata
    return header + question + answer_data


def wrap_packet(dns_data, ts, src_ip, dst_ip, src_port, dst_port):
    udp_len = 8 + len(dns_data)
    udp = struct.pack('!HHHH', src_port, dst_port, udp_len, 0)
    ip_total = 20 + udp_len
    ip_hdr = struct.pack('!BBHHHBBH4s4s',
                         0x45, 0, ip_total, 0, 0x4000,
                         64, 17, 0,
                         socket.inet_aton(src_ip),
                         socket.inet_aton(dst_ip))
    cksum = ip_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack('!H', cksum) + ip_hdr[12:]
    eth = b'\x00\x11\x22\x33\x44\x55\x66\x77\x88\x99\xaa\xbb' + struct.pack('!H', 0x0800)
    pkt = eth + ip_hdr + udp + dns_data
    return struct.pack('<IIII', ts, 0, len(pkt), len(pkt)) + pkt


def main():
    os.makedirs('/app/captures', exist_ok=True)
    packets = []
    ts = 1706745600
    srv = '10.0.0.53'
    cli = '10.0.0.100'

    # 1. Noise: query for example.com
    packets.append(wrap_packet(make_dns_query(9001, 'example.com', TYPE_A),
                               ts, cli, srv, 45000, 53))
    ts += 1

    # 2. SOA for services.lab
    soa_rd = (encode_name('ns1.services.lab.') +
              encode_name('hostmaster.services.lab.') +
              struct.pack('!IIIII', 2024020101, 3600, 900, 604800, 86400))
    packets.append(wrap_packet(
        make_dns_response(1001, 'services.lab', TYPE_SOA,
                          [('services.lab.', TYPE_SOA, 7200, soa_rd)]),
        ts, srv, cli, 53, 45001))
    ts += 1

    # 3. Noise: query for google.com
    packets.append(wrap_packet(make_dns_query(9002, 'google.com', TYPE_A),
                               ts, cli, srv, 45002, 53))
    ts += 1

    # 4. NS for services.lab
    packets.append(wrap_packet(
        make_dns_response(1002, 'services.lab', TYPE_NS,
                          [('services.lab.', TYPE_NS, 7200,
                            encode_name('ns1.services.lab.'))]),
        ts, srv, cli, 53, 45003))
    ts += 1

    # 5. A for api.services.lab
    packets.append(wrap_packet(
        make_dns_response(1003, 'api.services.lab', TYPE_A,
                          [('api.services.lab.', TYPE_A, 3600,
                            socket.inet_aton('10.2.0.10'))]),
        ts, srv, cli, 53, 45004))
    ts += 1

    # 6. AAAA for api.services.lab
    packets.append(wrap_packet(
        make_dns_response(1004, 'api.services.lab', TYPE_AAAA,
                          [('api.services.lab.', TYPE_AAAA, 3600,
                            ipaddress.IPv6Address('fd00:2::10').packed)]),
        ts, srv, cli, 53, 45005))
    ts += 1

    # 7. Noise: query for facebook.com AAAA
    packets.append(wrap_packet(make_dns_query(9003, 'facebook.com', TYPE_AAAA),
                               ts, cli, srv, 45006, 53))
    ts += 1

    # 8. cdn.services.lab CNAME + A (chain)
    packets.append(wrap_packet(
        make_dns_response(1005, 'cdn.services.lab', TYPE_A, [
            ('cdn.services.lab.', TYPE_CNAME, 3600,
             encode_name('origin.services.lab.')),
            ('origin.services.lab.', TYPE_A, 3600,
             socket.inet_aton('10.2.0.20'))]),
        ts, srv, cli, 53, 45007))
    ts += 1

    # 9. Noise: SERVFAIL response
    packets.append(wrap_packet(
        make_dns_response(9004, 'badquery.example.net', TYPE_A, [], rcode=2, aa=False),
        ts, srv, cli, 53, 45008))
    ts += 1

    # 10. MX for services.lab
    mx_rd = struct.pack('!H', 20) + encode_name('smtp.services.lab.')
    packets.append(wrap_packet(
        make_dns_response(1006, 'services.lab', TYPE_MX,
                          [('services.lab.', TYPE_MX, 7200, mx_rd)]),
        ts, srv, cli, 53, 45009))
    ts += 1

    # 11. A for smtp.services.lab
    packets.append(wrap_packet(
        make_dns_response(1007, 'smtp.services.lab', TYPE_A,
                          [('smtp.services.lab.', TYPE_A, 3600,
                            socket.inet_aton('10.2.0.30'))]),
        ts, srv, cli, 53, 45010))
    ts += 1

    # 12. A for ns1.services.lab
    packets.append(wrap_packet(
        make_dns_response(1008, 'ns1.services.lab', TYPE_A,
                          [('ns1.services.lab.', TYPE_A, 3600,
                            socket.inet_aton('10.2.0.1'))]),
        ts, srv, cli, 53, 45011))
    ts += 1

    # 13. TXT for services.lab
    txt = b'v=spf1 ip4:10.2.0.0/24 -all'
    txt_rd = bytes([len(txt)]) + txt
    packets.append(wrap_packet(
        make_dns_response(1009, 'services.lab', TYPE_TXT,
                          [('services.lab.', TYPE_TXT, 7200, txt_rd)]),
        ts, srv, cli, 53, 45012))
    ts += 1

    # 14. Wildcard *.apps.services.lab
    packets.append(wrap_packet(
        make_dns_response(1010, '*.apps.services.lab', TYPE_A,
                          [('*.apps.services.lab.', TYPE_A, 3600,
                            socket.inet_aton('10.2.1.0'))]),
        ts, srv, cli, 53, 45013))
    ts += 1

    # 15. Noise: response for other.example.org
    packets.append(wrap_packet(
        make_dns_response(9005, 'other.example.org', TYPE_A,
                          [('other.example.org.', TYPE_A, 3600,
                            socket.inet_aton('192.168.1.1'))]),
        ts, srv, cli, 53, 45014))

    with open('/app/captures/dns_traffic.pcap', 'wb') as f:
        f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for pkt in packets:
            f.write(pkt)
    print(f'Generated pcap with {len(packets)} packets')


if __name__ == '__main__':
    main()
