#!/usr/bin/env python3
"""XDP-style Load Balancer -- Pcap Packet Processor.

Reads /app/input.pcap + /app/config.json, produces /app/output.pcap + /app/stats.json.
Uses only Python 3 standard library.
"""

import struct
import json
import zlib

# ── pcap I/O ─────────────────────────────────────────────────────────

def read_pcap(path):
    with open(path, 'rb') as f:
        f.read(24)  # global header
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


# ── checksum helpers ─────────────────────────────────────────────────

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


def incr_csum16(old_csum, old_val, new_val):
    """Incremental checksum update for a 16-bit field change."""
    s = (~old_csum & 0xFFFF) + (~old_val & 0xFFFF) + new_val
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF


def incr_csum32(old_csum, old_ip, new_ip):
    """Incremental checksum update for a 32-bit (IP address) change."""
    c = incr_csum16(old_csum, (old_ip >> 16) & 0xFFFF, (new_ip >> 16) & 0xFFFF)
    c = incr_csum16(c, old_ip & 0xFFFF, new_ip & 0xFFFF)
    return c


# ── address helpers ──────────────────────────────────────────────────

def ip_to_int(s):
    parts = s.split('.')
    return (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(parts[3])


def int_to_ip(n):
    return f"{(n >> 24) & 0xFF}.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"


def mac_to_bytes(s):
    return bytes(int(x, 16) for x in s.split(':'))


# ── flow hashing / backend selection ─────────────────────────────────

def flow_hash(src_ip, dst_ip, src_port, dst_port, proto):
    key = struct.pack('!IIHHB', src_ip, dst_ip, src_port, dst_port, proto)
    return zlib.crc32(key) & 0xFFFFFFFF


def select_backend(h, backends_expanded):
    return backends_expanded[h % len(backends_expanded)]


# ── packet processing ────────────────────────────────────────────────

def process(input_path, config_path, output_path, stats_path):
    with open(config_path) as f:
        cfg = json.load(f)

    vip     = ip_to_int(cfg['vip'])
    lb_ip   = ip_to_int(cfg['lb_ip'])
    lb_mac  = mac_to_bytes(cfg['lb_mac'])
    backends = cfg['backends']
    for b in backends:
        b['_ip']  = ip_to_int(b['ip'])
        b['_mac'] = mac_to_bytes(b['mac'])

    expanded = []
    for i, b in enumerate(backends):
        expanded.extend([i] * b['weight'])

    packets = read_pcap(input_path)
    output  = []
    flow_table = {}
    summary = dict(total_input=len(packets), total_output=0, dropped=0,
                   load_balanced=0, icmp_replies=0, arp_replies=0, passthrough=0)
    flows_map = {}
    bstats = {b['ip']: dict(packet_count=0, byte_count=0) for b in backends}

    for ts_sec, ts_usec, raw, orig_len in packets:
        result = _process_pkt(raw, vip, lb_ip, lb_mac, backends, expanded,
                              flow_table, summary, flows_map, bstats)
        if result is not None:
            output.append((ts_sec, ts_usec, result, len(result)))
            summary['total_output'] += 1
        else:
            summary['dropped'] += 1

    write_pcap(output_path, output)

    flows_list = []
    for fk, info in flows_map.items():
        src_ip, dst_ip, sport, dport, proto = fk
        flows_list.append({
            'src_ip':       int_to_ip(src_ip),
            'dst_ip':       int_to_ip(dst_ip),
            'src_port':     sport,
            'dst_port':     dport,
            'protocol':     'TCP' if proto == 6 else 'UDP',
            'packet_count': info['count'],
            'backend_ip':   info['backend'],
        })

    backends_list = [{'ip': ip, 'packet_count': v['packet_count'],
                      'byte_count': v['byte_count']}
                     for ip, v in bstats.items()]

    stats = {'summary': summary, 'flows': flows_list, 'backends': backends_list}
    with open(stats_path, 'w') as f:
        json.dump(stats, f, indent=2)


def _process_pkt(raw, vip, lb_ip, lb_mac, backends, expanded,
                 flow_table, summary, flows_map, bstats):
    if len(raw) < 14:
        return None

    etype = struct.unpack('!H', raw[12:14])[0]
    eth_len = 14
    vlan_tag = None

    if etype == 0x8100:
        if len(raw) < 18:
            return None
        vlan_tag = raw[14:18]
        etype = struct.unpack('!H', raw[16:18])[0]
        eth_len = 18

    if etype == 0x0806:
        return _handle_arp(raw, eth_len, vip, lb_mac, summary)

    if etype != 0x0800:
        summary['passthrough'] += 1
        return raw

    if len(raw) < eth_len + 20:
        return None

    ihl   = (raw[eth_len] & 0x0F) * 4
    proto = raw[eth_len + 9]
    ip_csum = struct.unpack('!H', raw[eth_len + 10:eth_len + 12])[0]
    src_ip  = struct.unpack('!I', raw[eth_len + 12:eth_len + 16])[0]
    dst_ip  = struct.unpack('!I', raw[eth_len + 16:eth_len + 20])[0]

    if dst_ip != vip:
        summary['passthrough'] += 1
        return raw

    if proto == 1:
        return _handle_icmp(raw, eth_len, ihl, vip, lb_mac, summary)

    if proto not in (6, 17):
        summary['passthrough'] += 1
        return raw

    transport_off = eth_len + ihl
    min_transport = 20 if proto == 6 else 8
    if len(raw) < transport_off + min_transport:
        return None

    sport = struct.unpack('!H', raw[transport_off:transport_off + 2])[0]
    dport = struct.unpack('!H', raw[transport_off + 2:transport_off + 4])[0]

    fk = (src_ip, dst_ip, sport, dport, proto)
    if fk in flow_table:
        bidx = flow_table[fk]
    else:
        h = flow_hash(*fk)
        bidx = select_backend(h, expanded)
        flow_table[fk] = bidx
        flows_map[fk] = {'count': 0, 'backend': backends[bidx]['ip']}

    flows_map[fk]['count'] += 1
    backend = backends[bidx]
    summary['load_balanced'] += 1
    bstats[backend['ip']]['packet_count'] += 1
    bstats[backend['ip']]['byte_count']   += len(raw)

    # ── rewrite ──
    pkt = bytearray(raw)

    pkt[0:6]  = backend['_mac']
    pkt[6:12] = lb_mac

    new_src = lb_ip
    new_dst = backend['_ip']

    # Update IP header checksum for address changes
    new_ipc = incr_csum32(ip_csum, dst_ip, new_dst)
    pkt[eth_len + 10:eth_len + 12] = struct.pack('!H', new_ipc)

    pkt[eth_len + 12:eth_len + 16] = struct.pack('!I', new_src)
    pkt[eth_len + 16:eth_len + 20] = struct.pack('!I', new_dst)

    # Update transport checksum for pseudo-header changes
    if proto == 6:
        csum_off = transport_off + 16
    else:
        csum_off = transport_off + 6

    old_tc = struct.unpack('!H', pkt[csum_off:csum_off + 2])[0]
    new_tc = incr_csum32(old_tc, src_ip, new_src)
    pkt[csum_off:csum_off + 2] = struct.pack('!H', new_tc)

    # Normalize output framing
    if vlan_tag is not None:
        pkt = bytearray(pkt[:12]) + bytearray(pkt[16:])

    return bytes(pkt)


def _handle_arp(raw, eth_len, vip, lb_mac, summary):
    if len(raw) < eth_len + 28:
        return None
    oper = struct.unpack('!H', raw[eth_len + 6:eth_len + 8])[0]
    if oper != 1:
        summary['passthrough'] += 1
        return raw
    sha = raw[eth_len + 8:eth_len + 14]
    spa = raw[eth_len + 14:eth_len + 18]
    tpa = raw[eth_len + 24:eth_len + 28]
    tpa_int = struct.unpack('!I', tpa)[0]
    if tpa_int != vip:
        summary['passthrough'] += 1
        return raw

    reply = bytearray()
    reply += sha               # eth dst = original sender
    reply += lb_mac            # eth src = LB
    reply += struct.pack('!H', 0x0806)
    reply += struct.pack('!HHBBH', 1, 0x0800, 6, 4, 2)  # ARP reply
    reply += lb_mac            # SHA
    reply += spa               # SPA
    reply += sha               # THA
    reply += tpa               # TPA
    summary['arp_replies'] += 1
    return bytes(reply)


def _handle_icmp(raw, eth_len, ihl, vip, lb_mac, summary):
    icmp_off = eth_len + ihl
    if len(raw) < icmp_off + 8:
        return None
    if raw[icmp_off] != 8 or raw[icmp_off + 1] != 0:
        summary['passthrough'] += 1
        return raw

    pkt = bytearray(raw)

    pkt[0:6]  = raw[6:12]
    pkt[6:12] = lb_mac

    pkt[eth_len + 12:eth_len + 16] = raw[eth_len + 16:eth_len + 20]
    pkt[eth_len + 16:eth_len + 20] = raw[eth_len + 12:eth_len + 16]

    pkt[icmp_off] = 0

    old_icmp_csum = struct.unpack('!H', raw[icmp_off + 2:icmp_off + 4])[0]
    old_type_code = struct.unpack('!H', raw[icmp_off:icmp_off + 2])[0]
    new_type_code = struct.unpack('!H', pkt[icmp_off:icmp_off + 2])[0]
    new_csum = incr_csum16(old_icmp_csum, old_type_code, new_type_code)
    pkt[icmp_off + 2:icmp_off + 4] = struct.pack('!H', new_csum)

    summary['icmp_replies'] += 1
    return bytes(pkt)


if __name__ == '__main__':
    process('/app/input.pcap', '/app/config.json',
            '/app/output.pcap', '/app/stats.json')
    print("Done -- wrote /app/output.pcap and /app/stats.json")
