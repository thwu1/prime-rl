#!/usr/bin/env python3
"""Generate OSPF pcap file containing Router LSA and Hello packets.

The pcap encodes link cost information that is intentionally omitted
from topology.json, requiring pcap analysis to recover.

"""

import struct
import socket
import os


def inet_aton(ip):
    return socket.inet_aton(ip)


def internet_checksum(data):
    """Standard Internet checksum (RFC 1071)."""
    if len(data) % 2:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) | data[i + 1]
    while s >> 16:
        s = (s & 0xffff) + (s >> 16)
    return ~s & 0xffff


def make_ip_header(src, dst, payload_len):
    """Build IPv4 header for OSPF (protocol 89)."""
    hdr = struct.pack('!BBHHHBBH',
                      0x45, 0xc0, 20 + payload_len,
                      0, 0, 1, 89, 0)
    hdr += inet_aton(src) + inet_aton(dst)
    chk = internet_checksum(hdr)
    hdr = hdr[:10] + struct.pack('!H', chk) + hdr[12:]
    return hdr


def build_ospf_packet(msg_type, router_id, area_id, body):
    """Build OSPF packet (header + body) with correct checksum."""
    total_len = 24 + len(body)
    hdr = struct.pack('!BBH', 2, msg_type, total_len)
    hdr += inet_aton(router_id)
    hdr += inet_aton(area_id)
    hdr += struct.pack('!HH', 0, 0)
    hdr += b'\x00' * 8
    full = bytearray(hdr + body)
    chk_buf = bytearray(full)
    chk_buf[12] = 0
    chk_buf[13] = 0
    for i in range(16, 24):
        chk_buf[i] = 0
    chk = internet_checksum(bytes(chk_buf))
    full[12] = (chk >> 8) & 0xff
    full[13] = chk & 0xff
    return bytes(full)


def make_packet(src_ip, router_id, area_id, msg_type, body):
    """Build complete IP + OSPF packet."""
    ospf = build_ospf_packet(msg_type, router_id, area_id, body)
    ip = make_ip_header(src_ip, "224.0.0.5", len(ospf))
    return ip + ospf


def make_hello(mask, hello_int, options, prio, dead_int, dr, bdr, neighbors):
    """Build OSPF Hello body."""
    b = inet_aton(mask)
    b += struct.pack('!HBB', hello_int, options, prio)
    b += struct.pack('!I', dead_int)
    b += inet_aton(dr)
    b += inet_aton(bdr)
    for n in neighbors:
        b += inet_aton(n)
    return b


def make_router_link(link_id, link_data, link_type, metric):
    """Build Router LSA link entry (12 bytes)."""
    return (inet_aton(link_id) + inet_aton(link_data) +
            struct.pack('!BBH', link_type, 0, metric))


def fletcher_checksum(lsa_bytes):
    """Compute Fletcher-16 checksum for OSPF LSA (RFC 2328 Annex D)."""
    data = bytearray(lsa_bytes)
    data[16] = 0
    data[17] = 0
    buf = data[2:]  # skip LS Age
    c0, c1 = 0, 0
    for b in buf:
        c0 = (c0 + b) % 255
        c1 = (c1 + c0) % 255
    offset = 14  # checksum position within buf (0-based)
    x = int((len(buf) - offset - 1) * c0 - c1) % 255
    if x <= 0:
        x += 255
    y = 510 - c0 - x
    if y > 255:
        y -= 255
    data[16] = x
    data[17] = y
    return bytes(data)


def make_router_lsa(router_id, seq, flags, links):
    """Build Router LSA (type 1) with Fletcher checksum."""
    body = struct.pack('!BBH', flags, 0, len(links))
    for link in links:
        body += link
    total_len = 20 + len(body)
    lsa_hdr = struct.pack('!HBB', 1, 0x22, 1)   # age=1, options=E+DC, type=Router
    lsa_hdr += inet_aton(router_id)               # Link State ID
    lsa_hdr += inet_aton(router_id)               # Advertising Router
    lsa_hdr += struct.pack('!I', seq)             # Sequence Number
    lsa_hdr += struct.pack('!HH', 0, total_len)  # checksum placeholder, length
    return fletcher_checksum(lsa_hdr + body)


def make_external_lsa(ls_id, adv_router, seq, mask, e_bit, metric, fwd_addr, tag):
    """Build AS-External LSA (type 5) with Fletcher checksum."""
    body = inet_aton(mask)
    e_metric = (0x80000000 if e_bit else 0) | (metric & 0x00ffffff)
    body += struct.pack('!I', e_metric)
    body += inet_aton(fwd_addr)
    body += struct.pack('!I', tag)
    total_len = 20 + len(body)
    lsa_hdr = struct.pack('!HBB', 1, 0x22, 5)
    lsa_hdr += inet_aton(ls_id)
    lsa_hdr += inet_aton(adv_router)
    lsa_hdr += struct.pack('!I', seq)
    lsa_hdr += struct.pack('!HH', 0, total_len)
    return fletcher_checksum(lsa_hdr + body)


def make_ls_update(lsas):
    """Build LS Update body."""
    return struct.pack('!I', len(lsas)) + b''.join(lsas)


def write_pcap(filename, packets):
    """Write packets to pcap file (LINKTYPE_RAW = 101)."""
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'wb') as f:
        # Global header
        f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 101))
        ts = 1700000000
        for pkt in packets:
            ts += 1
            f.write(struct.pack('<IIII', ts, 0, len(pkt), len(pkt)))
            f.write(pkt)


def main():
    pkts = []

    # ===== OSPF Hello Packets =====

    # R1 Hello in Area 0 — DR=R2, BDR=R1
    pkts.append(make_packet("10.0.12.1", "1.1.1.1", "0.0.0.0", 1,
        make_hello("255.255.255.0", 10, 0x02, 1, 40,
                   "2.2.2.2", "1.1.1.1", ["2.2.2.2", "3.3.3.3"])))

    # R2 Hello in Area 0
    pkts.append(make_packet("10.0.12.2", "2.2.2.2", "0.0.0.0", 1,
        make_hello("255.255.255.0", 10, 0x02, 1, 40,
                   "2.2.2.2", "1.1.1.1", ["1.1.1.1", "3.3.3.3"])))

    # R3 Hello in Area 0
    pkts.append(make_packet("10.0.23.3", "3.3.3.3", "0.0.0.0", 1,
        make_hello("255.255.255.0", 10, 0x02, 1, 40,
                   "2.2.2.2", "1.1.1.1", ["1.1.1.1", "2.2.2.2"])))

    # R3 Hello in Area 1 — DR=R3 (only ABR on segment)
    pkts.append(make_packet("10.1.36.3", "3.3.3.3", "0.0.0.1", 1,
        make_hello("255.255.255.0", 10, 0x02, 1, 40,
                   "3.3.3.3", "0.0.0.0", ["5.5.5.5", "6.6.6.6"])))

    # R8 Hello in Area 2 — non-standard timers: hello=30s, dead=120s
    pkts.append(make_packet("10.2.78.8", "8.8.8.8", "0.0.0.2", 1,
        make_hello("255.255.255.0", 30, 0x02, 1, 120,
                   "0.0.0.0", "0.0.0.0", ["7.7.7.7", "2.2.2.2"])))

    # R4 Hello in Area 0
    pkts.append(make_packet("10.0.34.4", "4.4.4.4", "0.0.0.0", 1,
        make_hello("255.255.255.0", 10, 0x02, 1, 40,
                   "2.2.2.2", "1.1.1.1", ["3.3.3.3", "2.2.2.2"])))

    # ===== Router LSA Updates =====

    # R3 Router LSA for Area 0: links R1(12), R2(5), R4(8), loopback stub(0)
    r3_a0 = make_router_lsa("3.3.3.3", 0x80000007, 0x01, [
        make_router_link("1.1.1.1", "10.0.13.3", 1, 12),
        make_router_link("2.2.2.2", "10.0.23.3", 1, 5),
        make_router_link("4.4.4.4", "10.0.34.3", 1, 8),
        make_router_link("10.3.3.3", "255.255.255.255", 3, 0),
    ])
    pkts.append(make_packet("10.3.3.3", "3.3.3.3", "0.0.0.0", 4,
                            make_ls_update([r3_a0])))

    # R3 Router LSA for Area 1: links R5(20), R6(7)
    r3_a1 = make_router_lsa("3.3.3.3", 0x80000004, 0x01, [
        make_router_link("5.5.5.5", "10.1.35.3", 1, 20),
        make_router_link("6.6.6.6", "10.1.36.3", 1, 7),
    ])
    pkts.append(make_packet("10.3.3.3", "3.3.3.3", "0.0.0.1", 4,
                            make_ls_update([r3_a1])))

    # R2 Router LSA for Area 2: links R7(6), R8(15)
    r2_a2 = make_router_lsa("2.2.2.2", 0x80000003, 0x01, [
        make_router_link("7.7.7.7", "10.2.27.2", 1, 6),
        make_router_link("8.8.8.8", "10.2.28.2", 1, 15),
    ])
    pkts.append(make_packet("10.2.2.2", "2.2.2.2", "0.0.0.2", 4,
                            make_ls_update([r2_a2])))

    # ===== Noise: DB Description from R4 (OSPF type 2) =====
    dd_body = struct.pack('!HBB', 1500, 0x02, 0x07)
    dd_body += struct.pack('!I', 1234)
    pkts.append(make_packet("10.0.34.4", "4.4.4.4", "0.0.0.0", 2, dd_body))

    # ===== AS-External LSA Update from R4 =====
    ext_lsa = make_external_lsa(
        "172.16.0.0", "4.4.4.4", 0x80000002,
        "255.255.0.0", True, 20, "0.0.0.0", 0)
    pkts.append(make_packet("10.4.4.4", "4.4.4.4", "0.0.0.0", 4,
                            make_ls_update([ext_lsa])))

    write_pcap("/app/network/ospf_capture.pcap", pkts)
    print(f"Generated OSPF pcap with {len(pkts)} packets")


if __name__ == "__main__":
    main()
