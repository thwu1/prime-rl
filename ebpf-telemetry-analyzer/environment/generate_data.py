#!/usr/bin/env python3
"""Generate binary telemetry data files matching eBPF BPF-map dump formats,
plus a libpcap packet capture with DNS and TCP SYN traffic."""
import struct
import os

os.makedirs('/app/data', exist_ok=True)

def ip_to_int(ip_str):
    parts = ip_str.split('.')
    return (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(parts[3])

def pack_ct_key(src_ip, dst_ip, src_port, dst_port, proto):
    """ConntrackKey: 16 bytes. IPs/ports big-endian, proto u8, 3 pad."""
    return struct.pack('!IIHHBxxx',
        ip_to_int(src_ip), ip_to_int(dst_ip), src_port, dst_port, proto)

def pack_tcp_flags(syn=0, ack=0, fin=0, rst=0, psh=0, urg=0, ece=0, cwr=0, ns=0):
    """TcpFlagCounts: 36 bytes, all u32 little-endian."""
    return struct.pack('<IIIIIIIII', syn, ack, fin, rst, psh, urg, ece, cwr, ns)

def pack_ct_entry(is_dir_unknown, traffic_dir, seq_num, ack_num, tsval, tsecr,
                  ftx, frx, bytes_tx, bytes_rx, packets_tx, packets_rx,
                  eviction_time_ns, is_closing):
    """ConntrackEntry: 144 bytes."""
    data = struct.pack('<BBxx', is_dir_unknown, traffic_dir)      # 4
    data += struct.pack('<IIII', seq_num, ack_num, tsval, tsecr)  # 16
    data += pack_tcp_flags(**ftx)                                  # 36
    data += pack_tcp_flags(**frx)                                  # 36
    data += b'\x00' * 4                                            # 4 pad2
    data += struct.pack('<QQQQQ', bytes_tx, bytes_rx,
                        packets_tx, packets_rx, eviction_time_ns)  # 40
    data += struct.pack('<I', is_closing) + b'\x00' * 4            # 8
    return data  # total: 4+16+36+36+4+40+8 = 144

def pack_drop(drop_type, return_val, count, byte_count):
    """DropRecord: 24 bytes."""
    return struct.pack('<HxxiQQ', drop_type, return_val, count, byte_count)

def pack_dns(src_ip, dst_ip, src_port, dst_port, query_id, query_type,
             answer_count, response_code, is_response, timestamp_ns):
    """DnsEvent: 24 bytes."""
    data = struct.pack('!IIHHHH', ip_to_int(src_ip), ip_to_int(dst_ip),
                       src_port, dst_port, query_id, query_type)
    data += struct.pack('<H', answer_count)
    data += struct.pack('BB', response_code, is_response)
    data += struct.pack('<I', timestamp_ns & 0xFFFFFFFF)
    return data

def pack_retransmit(tcp_state, src_port, dst_port, src_ip, dst_ip, tcp_flags, af=2):
    """RetransmitEvent: 20 bytes."""
    return (struct.pack('<I', tcp_state) +
            struct.pack('!HHII', src_port, dst_port,
                        ip_to_int(src_ip), ip_to_int(dst_ip)) +
            struct.pack('BBxx', tcp_flags, af))

# =====================================================================
# CONNTRACK RECORDS (12 connections)
# =====================================================================
ct = []

# conn1: Healthy HTTP, both FINs seen -> TIME_WAIT
ct.append(pack_ct_key('10.0.1.10', '10.0.2.10', 45000, 80, 6) +
    pack_ct_entry(0, 1, 1000000, 2000000, 12345, 67890,
        {'syn':1,'ack':100,'fin':1,'psh':50},
        {'syn':1,'ack':100,'fin':1,'psh':45},
        524288, 1048576, 512, 1024, 1000000000000, 1))

# conn2: Half-open (SYN retries, no SYN-ACK)
ct.append(pack_ct_key('10.0.1.11', '10.0.2.10', 45001, 80, 6) +
    pack_ct_entry(0, 1, 500, 0, 0, 0,
        {'syn':3}, {},
        180, 0, 3, 0, 2000000000000, 0))

# conn3: RST storm (many RSTs both directions)
ct.append(pack_ct_key('10.0.1.12', '10.0.2.11', 45002, 443, 6) +
    pack_ct_entry(0, 1, 300000, 400000, 11111, 22222,
        {'syn':1,'ack':20,'rst':15,'psh':5},
        {'syn':1,'ack':20,'rst':12},
        8192, 4096, 41, 33, 3000000000000, 1))

# conn4: DNS over UDP, healthy query/response
ct.append(pack_ct_key('10.0.1.13', '10.0.2.12', 45003, 53, 17) +
    pack_ct_entry(0, 1, 0, 0, 0, 0, {}, {},
        64, 256, 1, 1, 4000000000000, 0))

# conn5: DNS over UDP, query without response
ct.append(pack_ct_key('10.0.1.14', '10.0.2.12', 45004, 53, 17) +
    pack_ct_entry(0, 1, 0, 0, 0, 0, {}, {},
        64, 0, 1, 0, 5000000000000, 0))

# conn6: Heavy retransmissions, both FINs -> TIME_WAIT
ct.append(pack_ct_key('10.0.1.15', '10.0.2.13', 45005, 8080, 6) +
    pack_ct_entry(0, 1, 5000000, 6000000, 33333, 44444,
        {'syn':1,'ack':200,'fin':1,'psh':100},
        {'syn':1,'ack':200,'fin':1,'psh':80},
        2097152, 1048576, 2000, 1000, 6000000000000, 1))

# conn7: Extremely asymmetric traffic (bulk upload to MySQL)
ct.append(pack_ct_key('10.0.1.16', '10.0.2.14', 45006, 3306, 6) +
    pack_ct_entry(0, 1, 8000000, 9000000, 55555, 66666,
        {'syn':1,'ack':500,'psh':400},
        {'syn':1,'ack':500,'psh':5},
        10485760, 4096, 5000, 506, 7000000000000, 0))

# conn8: Connection with associated drops
ct.append(pack_ct_key('10.0.1.17', '10.0.2.10', 45007, 80, 6) +
    pack_ct_entry(0, 1, 100000, 200000, 77777, 88888,
        {'syn':1,'ack':10}, {'syn':1,'ack':10},
        4096, 2048, 21, 11, 8000000000000, 0))

# conn9: Healthy Redis connection
ct.append(pack_ct_key('10.0.1.10', '10.0.2.15', 45008, 6379, 6) +
    pack_ct_entry(0, 1, 3000000, 4000000, 99999, 11111,
        {'syn':1,'ack':1000,'psh':500},
        {'syn':1,'ack':1000,'psh':500},
        524288, 524288, 1500, 1500, 9000000000000, 0))

# conn10: Pre-existing connection, direction unknown (no SYN seen)
ct.append(pack_ct_key('10.0.1.18', '10.0.2.16', 45009, 9090, 6) +
    pack_ct_entry(1, 0, 200000, 300000, 22222, 33333,
        {'ack':50,'psh':20}, {'ack':50,'psh':20},
        65536, 65536, 70, 70, 10000000000000, 0))

# conn11: SSH connection observed from ingress
ct.append(pack_ct_key('10.0.1.19', '10.0.2.17', 45010, 22, 6) +
    pack_ct_entry(0, 2, 7000000, 8000000, 44444, 55555,
        {'syn':1,'ack':300,'psh':150},
        {'syn':1,'ack':300,'psh':150},
        262144, 262144, 450, 450, 11000000000000, 0))

# conn12: FIN sent but not acknowledged by remote (FIN_WAIT)
ct.append(pack_ct_key('10.0.1.20', '10.0.2.18', 45011, 5432, 6) +
    pack_ct_entry(0, 1, 9000000, 10000000, 66666, 77777,
        {'syn':1,'ack':50,'fin':1,'psh':20},
        {'syn':1,'ack':50,'psh':15},
        32768, 16384, 72, 66, 12000000000000, 1))

with open('/app/data/conntrack_entries.bin', 'wb') as f:
    for r in ct:
        f.write(r)

# =====================================================================
# DROP RECORDS
# =====================================================================
drops = [
    pack_drop(1, -1, 5, 2500),      # IPTABLES_RULE_DROP
    pack_drop(6, -110, 3, 180),      # CONNTRACK_DROP
    pack_drop(3, -111, 2, 120),      # TCP_CONNECT_BASIC
    pack_drop(7, 0, 1, 64),          # UNKNOWN_DROP
]
with open('/app/data/drop_events.bin', 'wb') as f:
    for d in drops:
        f.write(d)

# =====================================================================
# DNS EVENTS
# =====================================================================
dns = [
    # Query/response pair for conn4 (matched, NOERROR, 2 answers)
    pack_dns('10.0.1.13','10.0.2.12', 45003, 53, 0x1234, 1, 0, 0, 0, 1000000),
    pack_dns('10.0.2.12','10.0.1.13', 53, 45003, 0x1234, 1, 2, 0, 1, 1000500),
    # Query for conn5 (no matching response)
    pack_dns('10.0.1.14','10.0.2.12', 45004, 53, 0x5678, 1, 0, 0, 0, 2000000),
    # AAAA query/response (NXDOMAIN, 0 answers)
    pack_dns('10.0.1.10','10.0.2.12', 50000, 53, 0xABCD, 28, 0, 0, 0, 3000000),
    pack_dns('10.0.2.12','10.0.1.10', 53, 50000, 0xABCD, 28, 0, 3, 1, 3000100),
    # A query/response (NOERROR, 1 answer)
    pack_dns('10.0.1.15','10.0.2.12', 50001, 53, 0xBEEF, 1, 0, 0, 0, 4000000),
    pack_dns('10.0.2.12','10.0.1.15', 53, 50001, 0xBEEF, 1, 1, 0, 1, 4000200),
]
with open('/app/data/dns_events.bin', 'wb') as f:
    for d in dns:
        f.write(d)

# =====================================================================
# TCP RETRANSMIT EVENTS
# =====================================================================
retx = []
# 25 retransmits for conn6 (10.0.1.15:45005 -> 10.0.2.13:8080)
for i in range(25):
    flags = 0x10 if i % 2 == 0 else 0x18  # ACK or ACK+PSH
    retx.append(pack_retransmit(1, 45005, 8080, '10.0.1.15', '10.0.2.13', flags))
# 2 retransmits for conn3 (RST storm connection)
retx.append(pack_retransmit(1, 45002, 443, '10.0.1.12', '10.0.2.11', 0x10))
retx.append(pack_retransmit(1, 45002, 443, '10.0.1.12', '10.0.2.11', 0x10))
# 1 retransmit for conn8 (dropped connection)
retx.append(pack_retransmit(1, 45007, 80, '10.0.1.17', '10.0.2.10', 0x10))

with open('/app/data/tcp_retransmits.bin', 'wb') as f:
    for r in retx:
        f.write(r)

# =====================================================================
# PCAP GENERATION
# =====================================================================

def ip_checksum(hdr):
    """Compute IPv4 header checksum over raw bytes."""
    if len(hdr) % 2:
        hdr = hdr + b'\x00'
    s = 0
    for i in range(0, len(hdr), 2):
        s += (hdr[i] << 8) | hdr[i + 1]
    s = (s >> 16) + (s & 0xFFFF)
    s += (s >> 16)
    return (~s) & 0xFFFF

def encode_dns_name(name):
    """Encode domain name in DNS wire format (length-prefixed labels + null)."""
    result = b''
    for label in name.split('.'):
        result += bytes([len(label)]) + label.encode('ascii')
    result += b'\x00'
    return result

def make_dns_query_payload(qid, qname, qtype):
    """Build DNS query message bytes."""
    header = struct.pack('!HHHHHH', qid, 0x0100, 1, 0, 0, 0)
    question = encode_dns_name(qname) + struct.pack('!HH', qtype, 1)
    return header + question

def make_dns_response_payload(qid, qname, qtype, rcode, answer_ips):
    """Build DNS response message bytes. answer_ips is a list of IPv4 strings for A records."""
    flags = 0x8180 | rcode
    ancount = len(answer_ips)
    header = struct.pack('!HHHHHH', qid, flags, 1, ancount, 0, 0)
    question = encode_dns_name(qname) + struct.pack('!HH', qtype, 1)
    answers = b''
    for ip_str in answer_ips:
        # NAME pointer to qname at offset 12, TYPE, CLASS, TTL, RDLENGTH, RDATA
        answers += struct.pack('!HHHIH', 0xC00C, qtype, 1, 300, 4)
        answers += struct.pack('!I', ip_to_int(ip_str))
    return header + question + answers

def make_ip_header(src_ip, dst_ip, payload_len, proto, ident=0):
    """Build IPv4 header (20 bytes) with correct checksum."""
    total_len = 20 + payload_len
    hdr = struct.pack('!BBHHHBBH',
        0x45, 0, total_len, ident, 0x4000, 64, proto, 0)
    hdr += struct.pack('!II', ip_to_int(src_ip), ip_to_int(dst_ip))
    cs = ip_checksum(hdr)
    hdr = hdr[:10] + struct.pack('!H', cs) + hdr[12:]
    return hdr

def make_ethernet(payload):
    """Wrap payload in Ethernet frame (type IPv4)."""
    return b'\x00\x11\x22\x33\x44\x55' + b'\x66\x77\x88\x99\xaa\xbb' + struct.pack('!H', 0x0800) + payload

def make_udp_packet(src_ip, dst_ip, src_port, dst_port, payload):
    """Build full Ethernet/IPv4/UDP packet."""
    udp_len = 8 + len(payload)
    udp = struct.pack('!HHHH', src_port, dst_port, udp_len, 0) + payload
    ip = make_ip_header(src_ip, dst_ip, len(udp), 17)
    return make_ethernet(ip + udp)

def make_tcp_syn_packet(src_ip, dst_ip, src_port, dst_port, seq=1000):
    """Build full Ethernet/IPv4/TCP SYN packet (no payload)."""
    tcp = struct.pack('!HHIIBBHHH',
        src_port, dst_port, seq, 0,
        0x50,   # data offset = 5 words (20 bytes)
        0x02,   # SYN flag
        65535, 0, 0)
    ip = make_ip_header(src_ip, dst_ip, len(tcp), 6)
    return make_ethernet(ip + tcp)

def pcap_record(ts_sec, ts_usec, pkt_data):
    """Build pcap packet record header + data."""
    return struct.pack('<IIII', ts_sec, ts_usec, len(pkt_data), len(pkt_data)) + pkt_data

# pcap global header: little-endian, v2.4, snaplen 65535, linktype Ethernet
pcap_global = struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)

pcap_packets = []

# Packet 1: TCP SYN conn1 (10.0.1.10:45000 -> 10.0.2.10:80)
pcap_packets.append(pcap_record(0, 0,
    make_tcp_syn_packet('10.0.1.10', '10.0.2.10', 45000, 80)))

# Packet 2: TCP SYN conn2 attempt 1 (10.0.1.11:45001 -> 10.0.2.10:80)
pcap_packets.append(pcap_record(0, 500000,
    make_tcp_syn_packet('10.0.1.11', '10.0.2.10', 45001, 80)))

# Packet 3: DNS query 0x1234 - api.cluster.local A
pcap_packets.append(pcap_record(1, 0,
    make_udp_packet('10.0.1.13', '10.0.2.12', 45003, 53,
        make_dns_query_payload(0x1234, 'api.cluster.local', 1))))

# Packet 4: DNS response 0x1234 - api.cluster.local A, NOERROR, 2 answers
pcap_packets.append(pcap_record(1, 500,
    make_udp_packet('10.0.2.12', '10.0.1.13', 53, 45003,
        make_dns_response_payload(0x1234, 'api.cluster.local', 1, 0,
            ['10.0.3.1', '10.0.3.2']))))

# Packet 5: TCP SYN conn2 attempt 2
pcap_packets.append(pcap_record(1, 500000,
    make_tcp_syn_packet('10.0.1.11', '10.0.2.10', 45001, 80, seq=1001)))

# Packet 6: DNS query 0x5678 - db.internal.svc A (no response)
pcap_packets.append(pcap_record(2, 0,
    make_udp_packet('10.0.1.14', '10.0.2.12', 45004, 53,
        make_dns_query_payload(0x5678, 'db.internal.svc', 1))))

# Packet 7: TCP SYN conn2 attempt 3
pcap_packets.append(pcap_record(2, 500000,
    make_tcp_syn_packet('10.0.1.11', '10.0.2.10', 45001, 80, seq=1002)))

# Packet 8: DNS query 0xABCD - cache.external.io AAAA
pcap_packets.append(pcap_record(3, 0,
    make_udp_packet('10.0.1.10', '10.0.2.12', 50000, 53,
        make_dns_query_payload(0xABCD, 'cache.external.io', 28))))

# Packet 9: DNS response 0xABCD - cache.external.io AAAA, NXDOMAIN, 0 answers
pcap_packets.append(pcap_record(3, 100,
    make_udp_packet('10.0.2.12', '10.0.1.10', 53, 50000,
        make_dns_response_payload(0xABCD, 'cache.external.io', 28, 3, []))))

# Packet 10: DNS query 0xBEEF - metrics.cluster.local A
pcap_packets.append(pcap_record(4, 0,
    make_udp_packet('10.0.1.15', '10.0.2.12', 50001, 53,
        make_dns_query_payload(0xBEEF, 'metrics.cluster.local', 1))))

# Packet 11: DNS response 0xBEEF - metrics.cluster.local A, NOERROR, 1 answer
pcap_packets.append(pcap_record(4, 200,
    make_udp_packet('10.0.2.12', '10.0.1.15', 53, 50001,
        make_dns_response_payload(0xBEEF, 'metrics.cluster.local', 1, 0,
            ['10.0.3.3']))))

# Packet 12: TCP SYN conn3 (10.0.1.12:45002 -> 10.0.2.11:443)
pcap_packets.append(pcap_record(5, 0,
    make_tcp_syn_packet('10.0.1.12', '10.0.2.11', 45002, 443)))

# Packet 13: TCP SYN conn9 (10.0.1.10:45008 -> 10.0.2.15:6379)
pcap_packets.append(pcap_record(6, 0,
    make_tcp_syn_packet('10.0.1.10', '10.0.2.15', 45008, 6379)))

with open('/app/data/capture.pcap', 'wb') as f:
    f.write(pcap_global)
    for p in pcap_packets:
        f.write(p)

# =====================================================================
# VERIFY FILE SIZES
# =====================================================================
for fname, expected in [
    ('conntrack_entries.bin', 12 * 160),
    ('drop_events.bin', 4 * 24),
    ('dns_events.bin', 7 * 24),
    ('tcp_retransmits.bin', 28 * 20)]:
    actual = os.path.getsize(f'/app/data/{fname}')
    assert actual == expected, f"{fname}: expected {expected}, got {actual}"
    print(f"OK {fname}: {actual} bytes")

pcap_size = os.path.getsize('/app/data/capture.pcap')
assert pcap_size > 24, f"capture.pcap too small: {pcap_size} bytes"
print(f"OK capture.pcap: {pcap_size} bytes ({len(pcap_packets)} packets)")

print("All telemetry data generated successfully.")
