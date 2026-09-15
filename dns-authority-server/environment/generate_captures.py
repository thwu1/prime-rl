#!/usr/bin/env python3
"""Generate reference DNS traffic capture as a pcap file.

Produces /app/reference.pcap containing query-response pairs from the
correctly-functioning DNS server. Each pair consists of a client query and
the expected server response, wrapped in Ethernet/IP/UDP headers.
"""

import struct
import socket
import os

# DNS record type constants
TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28
TYPE_SRV = 33
TYPE_OPT = 41
CLASS_IN = 1

# pcap file format constants
PCAP_MAGIC = 0xA1B2C3D4
PCAP_VER_MAJOR = 2
PCAP_VER_MINOR = 4
PCAP_SNAPLEN = 65535
PCAP_LINKTYPE_ETHERNET = 1

# Simulated network addresses
CLIENT_IP = "10.0.0.100"
SERVER_IP = "10.0.0.1"
CLIENT_MAC = b"\x02\x00\x00\x00\x00\x01"
SERVER_MAC = b"\x02\x00\x00\x00\x00\x02"
DNS_PORT = 5353
CLIENT_PORT_BASE = 42000


# ---------------------------------------------------------------------------
# pcap helpers
# ---------------------------------------------------------------------------

def pcap_global_header():
    return struct.pack("<IHHiIII", PCAP_MAGIC, PCAP_VER_MAJOR, PCAP_VER_MINOR,
                       0, 0, PCAP_SNAPLEN, PCAP_LINKTYPE_ETHERNET)


def pcap_packet_record(ts_sec, ts_usec, raw):
    return struct.pack("<IIII", ts_sec, ts_usec, len(raw), len(raw)) + raw


def _ip_checksum(header_bytes):
    if len(header_bytes) % 2:
        header_bytes += b"\x00"
    total = 0
    for i in range(0, len(header_bytes), 2):
        total += struct.unpack("!H", header_bytes[i:i + 2])[0]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def wrap_eth_ip_udp(dns_payload, src_ip, dst_ip, src_port, dst_port,
                    src_mac, dst_mac, ip_id=0):
    # UDP header
    udp_len = 8 + len(dns_payload)
    udp = struct.pack("!HHHH", src_port, dst_port, udp_len, 0) + dns_payload

    # IPv4 header (no options)
    ip_total = 20 + len(udp)
    ip_hdr = struct.pack("!BBHHHBBH4s4s",
                         0x45, 0, ip_total, ip_id, 0x4000, 64, 17, 0,
                         socket.inet_aton(src_ip), socket.inet_aton(dst_ip))
    chksum = _ip_checksum(ip_hdr)
    ip_hdr = struct.pack("!BBHHHBBH4s4s",
                         0x45, 0, ip_total, ip_id, 0x4000, 64, 17, chksum,
                         socket.inet_aton(src_ip), socket.inet_aton(dst_ip))

    # Ethernet header
    eth = dst_mac + src_mac + struct.pack("!H", 0x0800)

    return eth + ip_hdr + udp


# ---------------------------------------------------------------------------
# DNS wire-format helpers
# ---------------------------------------------------------------------------

def encode_name(name):
    out = b""
    for label in name.split("."):
        enc = label.encode("ascii")
        out += bytes([len(enc)]) + enc
    out += b"\x00"
    return out


def make_rr(name, rtype, ttl, rdata):
    out = encode_name(name)
    out += struct.pack("!HHIH", rtype, CLASS_IN, ttl, len(rdata))
    out += rdata
    return out


def make_a(ip):
    return socket.inet_aton(ip)


def make_aaaa(ip):
    return socket.inet_pton(socket.AF_INET6, ip)


def make_cname(target):
    return encode_name(target)


def make_ns(target):
    return encode_name(target)


def make_mx(priority, target):
    return struct.pack("!H", priority) + encode_name(target)


def make_txt(strings):
    out = b""
    for s in strings:
        raw = s.encode("utf-8")
        while len(raw) > 255:
            out += bytes([255]) + raw[:255]
            raw = raw[255:]
        out += bytes([len(raw)]) + raw
    return out


def make_soa(mname, rname, serial, refresh, retry, expire, minimum):
    out = encode_name(mname)
    out += encode_name(rname)
    out += struct.pack("!IIIII", serial, refresh, retry, expire, minimum)
    return out


def make_srv(priority, weight, port, target):
    return struct.pack("!HHH", priority, weight, port) + encode_name(target)


def build_query(qid, qname, qtype, rd=True, edns=False):
    flags = 0x0100 if rd else 0x0000
    arcount = 1 if edns else 0
    header = struct.pack("!HHHHHH", qid, flags, 1, 0, 0, arcount)
    question = encode_name(qname) + struct.pack("!HH", qtype, CLASS_IN)
    pkt = header + question
    if edns:
        # OPT pseudo-record: root name, type=41, udp=4096, ext-rcode=0, rdlen=0
        pkt += b"\x00" + struct.pack("!HHIH", TYPE_OPT, 4096, 0, 0)
    return pkt


def build_response(qid, qname, qtype, answers, rcode=0,
                   authority=None, additional=None, rd=True):
    if authority is None:
        authority = []
    if additional is None:
        additional = []
    flags = 0x8400  # QR=1, AA=1
    if rd:
        flags |= 0x0100
    flags |= rcode
    header = struct.pack("!HHHHHH", qid, flags, 1, len(answers),
                         len(authority), len(additional))
    question = encode_name(qname) + struct.pack("!HH", qtype, CLASS_IN)
    body = question
    for rr in answers:
        body += rr
    for rr in authority:
        body += rr
    for rr in additional:
        body += rr
    return header + body


# ---------------------------------------------------------------------------
# Main — generate all reference query-response pairs as pcap
# ---------------------------------------------------------------------------

def main():
    ttl = 3600

    # SOA record for negative-response authority sections
    neg_ttl = min(ttl, 86400)
    soa_rdata = make_soa("ns1.bench.example", "admin.bench.example",
                         2024010101, 3600, 900, 604800, 86400)
    soa_rr = make_rr("bench.example", TYPE_SOA, neg_ttl, soa_rdata)

    # (qid, qname, qtype, edns, answers, rcode, authority, additional)
    scenarios = []

    # 1: bench.example A -> two A records
    scenarios.append((0x1001, "bench.example", TYPE_A, False,
        [make_rr("bench.example", TYPE_A, ttl, make_a("192.0.2.1")),
         make_rr("bench.example", TYPE_A, ttl, make_a("192.0.2.2"))],
        0, [], []))

    # 2: www.bench.example A
    scenarios.append((0x1002, "www.bench.example", TYPE_A, False,
        [make_rr("www.bench.example", TYPE_A, ttl, make_a("192.0.2.10"))],
        0, [], []))

    # 3: cdn.bench.example A -> CNAME chain to A
    scenarios.append((0x1003, "cdn.bench.example", TYPE_A, False,
        [make_rr("cdn.bench.example", TYPE_CNAME, ttl, make_cname("www.bench.example")),
         make_rr("www.bench.example", TYPE_A, ttl, make_a("192.0.2.10"))],
        0, [], []))

    # 4: blog.bench.example A -> double CNAME chain to A
    scenarios.append((0x1004, "blog.bench.example", TYPE_A, False,
        [make_rr("blog.bench.example", TYPE_CNAME, ttl, make_cname("cdn.bench.example")),
         make_rr("cdn.bench.example", TYPE_CNAME, ttl, make_cname("www.bench.example")),
         make_rr("www.bench.example", TYPE_A, ttl, make_a("192.0.2.10"))],
        0, [], []))

    # 5: bench.example MX -> MX records + glue A in additional
    scenarios.append((0x1005, "bench.example", TYPE_MX, False,
        [make_rr("bench.example", TYPE_MX, ttl, make_mx(10, "mail.bench.example")),
         make_rr("bench.example", TYPE_MX, ttl, make_mx(20, "mail2.bench.example"))],
        0, [],
        [make_rr("mail.bench.example", TYPE_A, ttl, make_a("192.0.2.20")),
         make_rr("mail2.bench.example", TYPE_A, ttl, make_a("192.0.2.21"))]))

    # 6: bench.example TXT -> SPF with character-string encoding
    scenarios.append((0x1006, "bench.example", TYPE_TXT, False,
        [make_rr("bench.example", TYPE_TXT, ttl,
                 make_txt(["v=spf1 include:_spf.bench.example ~all"]))],
        0, [], []))

    # 7: _sip._tcp.bench.example SRV
    scenarios.append((0x1007, "_sip._tcp.bench.example", TYPE_SRV, False,
        [make_rr("_sip._tcp.bench.example", TYPE_SRV, ttl,
                 make_srv(10, 60, 5060, "sip.bench.example"))],
        0, [], []))

    # 8: nonexistent.deep.bench.example A -> NXDOMAIN + SOA in authority
    scenarios.append((0x1008, "nonexistent.deep.bench.example", TYPE_A, False,
        [], 3, [soa_rr], []))

    # 9: randomhost.bench.example A -> wildcard match
    scenarios.append((0x1009, "randomhost.bench.example", TYPE_A, False,
        [make_rr("randomhost.bench.example", TYPE_A, ttl, make_a("192.0.2.100"))],
        0, [], []))

    # 10: specific.bench.example A -> explicit overrides wildcard
    scenarios.append((0x100A, "specific.bench.example", TYPE_A, False,
        [make_rr("specific.bench.example", TYPE_A, ttl, make_a("192.0.2.200"))],
        0, [], []))

    # 11: bench.example A with EDNS0 -> A records + OPT in additional
    opt_rr = b"\x00" + struct.pack("!HHIH", TYPE_OPT, 4096, 0, 0)
    scenarios.append((0x100B, "bench.example", TYPE_A, True,
        [make_rr("bench.example", TYPE_A, ttl, make_a("192.0.2.1")),
         make_rr("bench.example", TYPE_A, ttl, make_a("192.0.2.2"))],
        0, [], [opt_rr]))

    # 12: WWW.BENCH.EXAMPLE A -> case-insensitive match
    scenarios.append((0x100C, "WWW.BENCH.EXAMPLE", TYPE_A, False,
        [make_rr("WWW.BENCH.EXAMPLE", TYPE_A, ttl, make_a("192.0.2.10"))],
        0, [], []))

    # 13: mail.bench.example MX -> NODATA + SOA in authority
    scenarios.append((0x100D, "mail.bench.example", TYPE_MX, False,
        [], 0, [soa_rr], []))

    # 14: www.bench.example AAAA
    scenarios.append((0x100E, "www.bench.example", TYPE_AAAA, False,
        [make_rr("www.bench.example", TYPE_AAAA, ttl, make_aaaa("2001:db8::10"))],
        0, [], []))

    # 15: bench.example SOA
    scenarios.append((0x100F, "bench.example", TYPE_SOA, False,
        [make_rr("bench.example", TYPE_SOA, ttl,
                 make_soa("ns1.bench.example", "admin.bench.example",
                          2024010101, 3600, 900, 604800, 86400))],
        0, [], []))

    # 16: bench.example NS
    scenarios.append((0x1010, "bench.example", TYPE_NS, False,
        [make_rr("bench.example", TYPE_NS, ttl, make_ns("ns1.bench.example")),
         make_rr("bench.example", TYPE_NS, ttl, make_ns("ns2.bench.example"))],
        0, [], []))

    # 17: _dmarc.bench.example TXT
    scenarios.append((0x1011, "_dmarc.bench.example", TYPE_TXT, False,
        [make_rr("_dmarc.bench.example", TYPE_TXT, ttl,
                 make_txt(["v=DMARC1; p=reject; rua=mailto:dmarc@bench.example"]))],
        0, [], []))

    # Build pcap
    pcap_data = pcap_global_header()
    base_ts = 1700000000
    ip_id = 1000

    for idx, (qid, qname, qtype, edns, answers, rcode, auth, addt) in enumerate(scenarios):
        ts = base_ts + idx
        client_port = CLIENT_PORT_BASE + idx

        # Build DNS query and response payloads
        query_dns = build_query(qid, qname, qtype, rd=True, edns=edns)
        response_dns = build_response(qid, qname, qtype, answers,
                                      rcode=rcode, authority=auth, additional=addt)

        # Wrap in Ethernet/IP/UDP and add to pcap
        q_frame = wrap_eth_ip_udp(query_dns, CLIENT_IP, SERVER_IP,
                                  client_port, DNS_PORT, CLIENT_MAC, SERVER_MAC,
                                  ip_id=ip_id)
        pcap_data += pcap_packet_record(ts, 0, q_frame)
        ip_id += 1

        r_frame = wrap_eth_ip_udp(response_dns, SERVER_IP, CLIENT_IP,
                                  DNS_PORT, client_port, SERVER_MAC, CLIENT_MAC,
                                  ip_id=ip_id)
        pcap_data += pcap_packet_record(ts, 500000, r_frame)
        ip_id += 1

    with open("/app/reference.pcap", "wb") as f:
        f.write(pcap_data)

    print(f"Generated reference.pcap with {len(scenarios)} query-response pairs "
          f"({len(scenarios) * 2} packets)")


if __name__ == "__main__":
    main()
