#!/usr/bin/env python3
"""
IPv6 Traffic Security Audit — Solution

Parses PCAP captures, identifies IPv6 protocol violations and attack patterns,
classifies each flow, and generates nftables firewall rules.
"""

import struct
import socket
import json
from pathlib import Path

# Extension header Next Header values
EXT_NH = {
    0: 'hop-by-hop', 43: 'routing', 44: 'fragment',
    51: 'authentication', 50: 'esp', 60: 'destination',
}


def read_pcap(filepath):
    """Read raw packets from a pcap file (DLT_RAW)."""
    packets = []
    with open(filepath, 'rb') as f:
        ghdr = f.read(24)
        if len(ghdr) < 24:
            return packets
        magic = struct.unpack('<I', ghdr[:4])[0]
        if magic == 0xa1b2c3d4:
            endian = '<'
        elif magic == 0xd4c3b2a1:
            endian = '>'
        else:
            return packets
        while True:
            rec = f.read(16)
            if len(rec) < 16:
                break
            caplen = struct.unpack(f'{endian}I', rec[8:12])[0]
            data = f.read(caplen)
            if len(data) < caplen:
                break
            packets.append(data)
    return packets


def parse_ipv6(data):
    """Parse IPv6 header and walk extension header chain."""
    if len(data) < 40:
        return None

    w = struct.unpack('!I', data[:4])[0]
    version = (w >> 28) & 0xF
    pl = struct.unpack('!H', data[4:6])[0]
    nh = data[6]
    hop = data[7]
    src = socket.inet_ntop(socket.AF_INET6, data[8:24])
    dst = socket.inet_ntop(socket.AF_INET6, data[24:40])

    ext_headers = []
    offset = 40
    cur = nh
    frag_list = []
    routing_types = []
    hbh_pos = None
    hdr_counts = {}
    chain_idx = 0

    while cur in EXT_NH and offset < len(data):
        ext_headers.append(EXT_NH[cur])
        hdr_counts[cur] = hdr_counts.get(cur, 0) + 1

        if cur == 0:
            # Hop-by-Hop Options
            if hbh_pos is None:
                hbh_pos = chain_idx
            ext_nh = data[offset]
            ext_len = data[offset + 1]
            offset += (ext_len + 1) * 8
            cur = ext_nh

        elif cur == 43:
            # Routing Header
            ext_nh = data[offset]
            ext_len = data[offset + 1]
            rt_type = data[offset + 2]
            routing_types.append(rt_type)
            offset += (ext_len + 1) * 8
            cur = ext_nh

        elif cur == 44:
            # Fragment Header (fixed 8 bytes)
            ext_nh = data[offset]
            off_m = struct.unpack('!H', data[offset + 2:offset + 4])[0]
            frag_off = (off_m >> 3) & 0x1FFF
            frag_m = bool(off_m & 1)
            frag_id = struct.unpack('!I', data[offset + 4:offset + 8])[0]
            frag_data_len = pl - (offset - 40) - 8
            frag_list.append({
                'offset': frag_off,
                'm_flag': frag_m,
                'id': frag_id,
                'data_len': frag_data_len,
            })
            offset += 8
            cur = ext_nh

        elif cur == 60:
            # Destination Options
            ext_nh = data[offset]
            ext_len = data[offset + 1]
            offset += (ext_len + 1) * 8
            cur = ext_nh

        elif cur == 51:
            # Authentication Header
            ext_nh = data[offset]
            ext_len = data[offset + 1]
            offset += (ext_len + 2) * 4
            cur = ext_nh

        elif cur == 50:
            # ESP — opaque, stop
            break

        chain_idx += 1

    return {
        'src': src, 'dst': dst, 'version': version,
        'payload_length': pl, 'next_header': nh, 'hop_limit': hop,
        'ext_headers': ext_headers, 'frags': frag_list,
        'routing_types': routing_types, 'hbh_pos': hbh_pos,
        'hdr_counts': hdr_counts,
    }


def classify_flow(parsed_pkts):
    """Classify a flow based on IPv6 protocol analysis."""
    all_ext = []
    routing_types = set()
    frag_ranges = []
    oversized = False
    tiny_frag = False
    hbh_not_first = False
    dup_header = False

    for p in parsed_pkts:
        if not p:
            continue
        if not all_ext:
            all_ext = list(p['ext_headers'])

        for rt in p['routing_types']:
            routing_types.add(rt)

        for fi in p['frags']:
            start = fi['offset'] * 8
            end = start + fi['data_len']
            frag_ranges.append((start, end))
            if fi['offset'] * 8 + fi['data_len'] > 65535:
                oversized = True
            if fi['offset'] == 0 and fi['m_flag'] and fi['data_len'] < 20:
                tiny_frag = True

        if p['hbh_pos'] is not None and p['hbh_pos'] > 0:
            hbh_not_first = True

        for nh_val, count in p['hdr_counts'].items():
            if nh_val == 60:
                if count > 2:
                    dup_header = True
            else:
                if count > 1:
                    dup_header = True

    # Check for overlapping fragments
    overlapping = False
    for i in range(len(frag_ranges)):
        for j in range(i + 1, len(frag_ranges)):
            s1, e1 = frag_ranges[i]
            s2, e2 = frag_ranges[j]
            if s1 < e2 and s2 < e1:
                overlapping = True

    # Classification priority: most specific/dangerous first
    if 0 in routing_types:
        return ('deprecated_routing', 'high', all_ext,
                'Routing Header Type 0 detected; deprecated by RFC 5095 '
                'due to traffic amplification vulnerability')
    if overlapping:
        return ('fragment_evasion', 'high', all_ext,
                'Overlapping IPv6 fragments detected; used to evade '
                'stateless packet inspection')
    if tiny_frag:
        return ('fragment_evasion', 'high', all_ext,
                'First fragment too small for complete transport header; '
                'firewall evasion technique (RFC 1858)')
    if oversized:
        return ('oversized_reassembly', 'critical', all_ext,
                'Fragment offset plus data length exceeds maximum IPv6 '
                'payload size (65535 bytes); potential host crash')
    if hbh_not_first:
        return ('header_chain_violation', 'medium', all_ext,
                'Hop-by-Hop Options not first extension header; '
                'violates RFC 8200 Section 4.1')
    if dup_header:
        return ('header_chain_violation', 'medium', all_ext,
                'Duplicate extension header in chain; '
                'violates RFC 8200 Section 4.1')

    return ('legitimate', 'none', all_ext, None)


def generate_rules(path):
    """Generate nftables firewall rules for IPv6 security."""
    rules = """\
#!/usr/sbin/nft -f

flush ruleset

table ip6 ipv6_security {
    chain input {
        type filter hook input priority filter; policy accept;

        # Block deprecated Routing Header Type 0 (RFC 5095)
        rt type 0 counter drop

        # Drop all IPv6 fragments at the firewall
        # Prevents overlapping fragment evasion, tiny fragment attacks,
        # and oversized reassembly denial-of-service
        exthdr frag exists counter drop

        # Allow essential ICMPv6 for IPv6 operation
        icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert, nd-router-solicit, nd-router-advert } accept
        icmpv6 type { echo-request, echo-reply, packet-too-big, destination-unreachable } accept

        # Connection tracking
        ct state established,related accept
        ct state invalid drop
    }

    chain forward {
        type filter hook forward priority filter; policy drop;

        rt type 0 counter drop
        exthdr frag exists counter drop

        icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert, nd-router-solicit, nd-router-advert } accept
        icmpv6 type { echo-request, echo-reply, packet-too-big } accept

        ct state established,related accept
        ct state invalid drop
    }
}
"""
    with open(path, 'w') as f:
        f.write(rules)


def main():
    captures = sorted(Path('/app/captures').glob('*.pcap'))
    flows = {}

    for cap in captures:
        flow_id = cap.stem
        pkts = read_pcap(str(cap))
        parsed = [parse_ipv6(p) for p in pkts]
        parsed = [p for p in parsed if p is not None]
        if not parsed:
            continue

        classification, severity, ext_hdrs, violation = classify_flow(parsed)
        flows[flow_id] = {
            'classification': classification,
            'src_addr': parsed[0]['src'],
            'dst_addr': parsed[0]['dst'],
            'extension_headers': ext_hdrs,
            'violation_description': violation,
            'threat_severity': severity,
        }

    legit = sum(1 for f in flows.values() if f['classification'] == 'legitimate')
    categories = sorted(set(
        f['classification'] for f in flows.values()
        if f['classification'] != 'legitimate'
    ))

    audit = {
        'flows': flows,
        'summary': {
            'total_flows': len(flows),
            'legitimate_count': legit,
            'malicious_count': len(flows) - legit,
            'threat_categories': categories,
        },
    }

    with open('/app/audit.json', 'w') as f:
        json.dump(audit, f, indent=2)

    generate_rules('/app/rules.nft')
    print(f"Analyzed {len(flows)} flows: {legit} legitimate, "
          f"{len(flows) - legit} malicious")


if __name__ == '__main__':
    main()
