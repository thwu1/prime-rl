#!/usr/bin/env python3
"""XDP-style Load Balancer Packet Processor — Complete Implementation.

Reads /app/input.pcap + /app/config.json
Produces /app/output.pcap + /app/stats.json
"""


import struct
import json
import zlib


# ── pcap I/O ───────────────────────────────────────────────────────

def read_pcap(path):
    with open(path, 'rb') as f:
        f.read(24)
        packets = []
        while True:
            rec = f.read(16)
            if len(rec) < 16:
                break
            ts_sec, ts_usec, incl_len, orig_len = struct.unpack('<IIII', rec)
            data = f.read(incl_len)
            if len(data) < incl_len:
                break
            packets.append((ts_sec, ts_usec, data, orig_len))
    return packets


def write_pcap(path, packets):
    with open(path, 'wb') as f:
        f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for ts_sec, ts_usec, data, orig_len in packets:
            f.write(struct.pack('<IIII', ts_sec, ts_usec, len(data), orig_len))
            f.write(data)


# ── checksum ────────────────────────────────────────────────────────

def compute_checksum(data):
    """RFC 1071 one's complement checksum."""
    if len(data) % 2:
        data = data + b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) | data[i + 1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF


# ── address helpers ──────────────────────────────────────────────────

def ip_to_int(s):
    parts = s.split('.')
    return (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(parts[3])


def int_to_ip(n):
    return f"{(n >> 24) & 0xFF}.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"


def mac_to_bytes(s):
    return bytes(int(x, 16) for x in s.split(':'))


# ── flow hashing ─────────────────────────────────────────────────────

def flow_hash(src_ip, dst_ip, src_port, dst_port, proto):
    key = struct.pack('!IIHHB', src_ip, dst_ip, src_port, dst_port, proto)
    return zlib.crc32(key) & 0xFFFFFFFF


# ── main processor ───────────────────────────────────────────────────

def process_packets():
    with open('/app/config.json') as f:
        cfg = json.load(f)

    vip = ip_to_int(cfg['vip'])
    lb_ip = ip_to_int(cfg['lb_ip'])
    lb_mac = mac_to_bytes(cfg['lb_mac'])
    backends = cfg['backends']
    for b in backends:
        b['_ip'] = ip_to_int(b['ip'])
        b['_mac'] = mac_to_bytes(b['mac'])

    # Build weighted backend selection pool
    pool = []
    for i, b in enumerate(backends):
        pool.extend([i] * b['weight'])

    packets = read_pcap('/app/input.pcap')
    output = []
    flow_table = {}
    summary = dict(total_input=len(packets), total_output=0, dropped=0,
                   load_balanced=0, icmp_replies=0, arp_replies=0, passthrough=0)
    flows_map = {}
    bstats = {b['ip']: dict(packet_count=0, byte_count=0) for b in backends}

    for ts_sec, ts_usec, raw, orig_len in packets:
        result = _process_pkt(raw, vip, lb_ip, lb_mac, backends, pool,
                              flow_table, summary, flows_map, bstats)
        if result is not None:
            output.append((ts_sec, ts_usec, result, len(result)))
            summary['total_output'] += 1
        else:
            summary['dropped'] += 1

    write_pcap('/app/output.pcap', output)

    flows_list = []
    for fk, info in flows_map.items():
        src_ip, dst_ip, sport, dport, proto = fk
        flows_list.append({
            'src_ip': int_to_ip(src_ip),
            'dst_ip': int_to_ip(dst_ip),
            'src_port': sport,
            'dst_port': dport,
            'protocol': 'TCP' if proto == 6 else 'UDP',
            'packet_count': info['count'],
            'backend_ip': info['backend'],
        })

    backends_list = [{'ip': ip, 'packet_count': v['packet_count'],
                      'byte_count': v['byte_count']}
                     for ip, v in bstats.items()]

    stats = {'summary': summary, 'flows': flows_list, 'backends': backends_list}
    with open('/app/stats.json', 'w') as f:
        json.dump(stats, f, indent=2)

    print("Done -- wrote /app/output.pcap and /app/stats.json")


def _process_pkt(raw, vip, lb_ip, lb_mac, backends, pool,
                 flow_table, summary, flows_map, bstats):
    # Drop packets too short for Ethernet
    if len(raw) < 14:
        return None

    # Parse Ethernet header, handle 802.1Q VLAN
    etype = struct.unpack('!H', raw[12:14])[0]
    eth_len = 14
    vlan_tag = None

    if etype == 0x8100:
        if len(raw) < 18:
            return None
        vlan_tag = raw[14:18]
        etype = struct.unpack('!H', raw[16:18])[0]
        eth_len = 18

    # ARP handling
    if etype == 0x0806:
        return _handle_arp(raw, eth_len, vip, lb_mac, summary)

    # Non-IPv4: passthrough (IPv6, etc.)
    if etype != 0x0800:
        summary['passthrough'] += 1
        return raw

    # Validate minimum IP header
    if len(raw) < eth_len + 20:
        return None

    ihl = (raw[eth_len] & 0x0F) * 4
    proto = raw[eth_len + 9]
    src_ip = struct.unpack('!I', raw[eth_len + 12:eth_len + 16])[0]
    dst_ip = struct.unpack('!I', raw[eth_len + 16:eth_len + 20])[0]

    # Only process packets destined for the VIP
    if dst_ip != vip:
        summary['passthrough'] += 1
        return raw

    # ICMP echo request handling
    if proto == 1:
        return _handle_icmp(raw, eth_len, ihl, vip, lb_mac, summary)

    # Only load-balance TCP and UDP
    if proto not in (6, 17):
        summary['passthrough'] += 1
        return raw

    transport_off = eth_len + ihl
    min_transport = 20 if proto == 6 else 8
    if len(raw) < transport_off + min_transport:
        return None

    sport = struct.unpack('!H', raw[transport_off:transport_off + 2])[0]
    dport = struct.unpack('!H', raw[transport_off + 2:transport_off + 4])[0]

    # Flow-based consistent backend selection
    fk = (src_ip, dst_ip, sport, dport, proto)
    if fk in flow_table:
        bidx = flow_table[fk]
    else:
        h = flow_hash(*fk)
        bidx = pool[h % len(pool)]
        flow_table[fk] = bidx
        flows_map[fk] = {'count': 0, 'backend': backends[bidx]['ip']}

    flows_map[fk]['count'] += 1
    backend = backends[bidx]
    summary['load_balanced'] += 1
    bstats[backend['ip']]['packet_count'] += 1
    bstats[backend['ip']]['byte_count'] += len(raw)

    # ── Rewrite packet ──
    pkt = bytearray(raw)

    # Rewrite MACs: dst = backend, src = LB
    pkt[0:6] = backend['_mac']
    pkt[6:12] = lb_mac

    new_src = lb_ip
    new_dst = backend['_ip']

    # Rewrite IPs
    pkt[eth_len + 12:eth_len + 16] = struct.pack('!I', new_src)
    pkt[eth_len + 16:eth_len + 20] = struct.pack('!I', new_dst)

    # Recompute IP header checksum from scratch
    ip_hdr = bytearray(pkt[eth_len:eth_len + ihl])
    ip_hdr[10:12] = b'\x00\x00'
    new_ip_csum = compute_checksum(bytes(ip_hdr))
    pkt[eth_len + 10:eth_len + 12] = struct.pack('!H', new_ip_csum)

    # Update transport-layer checksum
    if proto == 6:
        csum_off = transport_off + 16  # TCP checksum offset
    else:
        csum_off = transport_off + 6   # UDP checksum offset

    old_tc = struct.unpack('!H', raw[transport_off + (16 if proto == 6 else 6):
                                     transport_off + (18 if proto == 6 else 8)])[0]

    if proto == 17 and old_tc == 0:
        # UDP checksum disabled (RFC 768) — preserve zero
        pass
    else:
        # Recompute transport checksum from scratch with new pseudo-header
        transport_data = bytearray(pkt[transport_off:])
        if proto == 6:
            transport_data[16:18] = b'\x00\x00'
        else:
            transport_data[6:8] = b'\x00\x00'
        pseudo = (struct.pack('!I', new_src) + struct.pack('!I', new_dst) +
                  struct.pack('!BBH', 0, proto, len(transport_data)))
        new_tc = compute_checksum(pseudo + bytes(transport_data))
        pkt[csum_off:csum_off + 2] = struct.pack('!H', new_tc)

    return bytes(pkt)


def _handle_arp(raw, eth_len, vip, lb_mac, summary):
    if len(raw) < eth_len + 28:
        return None
    oper = struct.unpack('!H', raw[eth_len + 6:eth_len + 8])[0]
    if oper != 1:  # Not a request
        summary['passthrough'] += 1
        return raw

    sha = raw[eth_len + 8:eth_len + 14]   # requester MAC
    spa = raw[eth_len + 14:eth_len + 18]   # requester IP
    tpa = raw[eth_len + 24:eth_len + 28]   # target IP (should be VIP)
    tpa_int = struct.unpack('!I', tpa)[0]

    if tpa_int != vip:
        summary['passthrough'] += 1
        return raw

    # Build ARP reply
    reply = bytearray()
    reply += sha                               # eth dst = requester
    reply += lb_mac                            # eth src = LB
    reply += struct.pack('!H', 0x0806)         # ethertype
    reply += struct.pack('!HHBBH', 1, 0x0800, 6, 4, 2)  # ARP reply header
    reply += lb_mac                            # SHA = LB MAC
    reply += tpa                               # SPA = VIP
    reply += sha                               # THA = requester MAC
    reply += spa                               # TPA = requester IP

    summary['arp_replies'] += 1
    return bytes(reply)


def _handle_icmp(raw, eth_len, ihl, vip, lb_mac, summary):
    icmp_off = eth_len + ihl
    if len(raw) < icmp_off + 8:
        return None

    # Only respond to echo request (type 8, code 0)
    if raw[icmp_off] != 8 or raw[icmp_off + 1] != 0:
        summary['passthrough'] += 1
        return raw

    pkt = bytearray(raw)

    # Swap MACs: dst = original src, src = LB MAC
    pkt[0:6] = raw[6:12]
    pkt[6:12] = lb_mac

    # Swap IPs: src = VIP (original dst), dst = requester (original src)
    pkt[eth_len + 12:eth_len + 16] = raw[eth_len + 16:eth_len + 20]
    pkt[eth_len + 16:eth_len + 20] = raw[eth_len + 12:eth_len + 16]

    # Change ICMP type from echo request (8) to echo reply (0)
    pkt[icmp_off] = 0

    # Recompute ICMP checksum from scratch
    icmp_data = bytearray(pkt[icmp_off:])
    icmp_data[2:4] = b'\x00\x00'
    new_icmp_csum = compute_checksum(bytes(icmp_data))
    pkt[icmp_off + 2:icmp_off + 4] = struct.pack('!H', new_icmp_csum)

    # Recompute IP header checksum from scratch
    ip_hdr = bytearray(pkt[eth_len:eth_len + ihl])
    ip_hdr[10:12] = b'\x00\x00'
    new_ip_csum = compute_checksum(bytes(ip_hdr))
    pkt[eth_len + 10:eth_len + 12] = struct.pack('!H', new_ip_csum)

    summary['icmp_replies'] += 1
    return bytes(pkt)


if __name__ == '__main__':
    process_packets()
