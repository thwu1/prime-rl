#!/usr/bin/env python3
"""
Network telemetry flow analyzer.

Parses binary BPF map dumps (conntrack, drops, DNS, retransmits),
extracts DNS domain names and statistics from pcap via direct binary
parsing, reads anomaly thresholds from config, correlates across
sources, infers TCP state, detects anomalies, and produces a JSON report.
"""
import struct
import json
import socket
import yaml


# =====================================================================
# Constants
# =====================================================================
DROP_TYPE_NAMES = {
    1: 'IPTABLES_RULE_DROP', 2: 'IPTABLES_NAT_DROP',
    3: 'TCP_CONNECT_BASIC', 4: 'TCP_ACCEPT_BASIC',
    5: 'TCP_CLOSE_BASIC', 6: 'CONNTRACK_DROP', 7: 'UNKNOWN_DROP',
}
QUERY_TYPE_NAMES = {
    1: 'A', 2: 'NS', 5: 'CNAME', 15: 'MX', 16: 'TXT',
    28: 'AAAA', 33: 'SRV', 255: 'ANY',
}
RCODE_NAMES = {
    0: 'NOERROR', 1: 'FORMERR', 2: 'SERVFAIL',
    3: 'NXDOMAIN', 4: 'NOTIMP', 5: 'REFUSED',
}


# =====================================================================
# Helpers
# =====================================================================
def int_to_ip(val):
    return socket.inet_ntoa(struct.pack('!I', val))


def conn_key(c):
    return f"{c['src_ip']}:{c['src_port']}->{c['dst_ip']}:{c['dst_port']}"


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


# =====================================================================
# Parsers
# =====================================================================
def parse_tcp_flags(data, offset=0):
    fields = struct.unpack_from('<IIIIIIIII', data, offset)
    return dict(zip(
        ('syn', 'ack', 'fin', 'rst', 'psh', 'urg', 'ece', 'cwr', 'ns'),
        fields))


def infer_tcp_state(flags_tx, flags_rx, proto):
    if proto == 17:
        return 'ACTIVE'
    # RST overrides everything
    if flags_tx['rst'] > 0 or flags_rx['rst'] > 0:
        return 'RESET'
    # SYN asymmetry
    if flags_tx['syn'] > 0 and flags_rx['syn'] == 0:
        return 'SYN_SENT'
    if flags_tx['syn'] == 0 and flags_rx['syn'] > 0:
        return 'SYN_RECV'
    # FIN states
    if flags_tx['fin'] > 0 and flags_rx['fin'] > 0:
        return 'TIME_WAIT'
    if flags_tx['fin'] > 0 and flags_rx['fin'] == 0:
        return 'FIN_WAIT'
    if flags_tx['fin'] == 0 and flags_rx['fin'] > 0:
        return 'CLOSE_WAIT'
    return 'ESTABLISHED'


def parse_conntrack(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()

    record_size = 160
    connections = []
    offset = 0
    dir_map = {0: 'unknown', 1: 'egress', 2: 'ingress'}

    while offset + record_size <= len(data):
        # Key: 16 bytes, big-endian network fields
        src_ip, dst_ip, src_port, dst_port, proto = struct.unpack_from(
            '!IIHHBxxx', data, offset)

        # Entry: 144 bytes at offset+16
        eo = offset + 16
        is_dir_unknown, traffic_dir = struct.unpack_from('<BBxx', data, eo)
        seq, ack, tsval, tsecr = struct.unpack_from('<IIII', data, eo + 4)
        flags_tx = parse_tcp_flags(data, eo + 20)
        flags_rx = parse_tcp_flags(data, eo + 56)
        # pad2 at eo+92 (4 bytes)
        bytes_tx, bytes_rx, pkts_tx, pkts_rx, evict = struct.unpack_from(
            '<QQQQQ', data, eo + 96)
        is_closing = struct.unpack_from('<I', data, eo + 136)[0]

        state = infer_tcp_state(flags_tx, flags_rx, proto)

        connections.append({
            'src_ip': int_to_ip(src_ip),
            'dst_ip': int_to_ip(dst_ip),
            'src_port': src_port,
            'dst_port': dst_port,
            'proto': 'TCP' if proto == 6 else 'UDP',
            'state': state,
            'direction': dir_map.get(traffic_dir, 'unknown'),
            'is_direction_unknown': bool(is_dir_unknown),
            'bytes_tx': bytes_tx,
            'bytes_rx': bytes_rx,
            'packets_tx': pkts_tx,
            'packets_rx': pkts_rx,
            'retransmit_count': 0,
            'flags_summary': {'tx': flags_tx, 'rx': flags_rx},
            'is_closing': bool(is_closing),
            'eviction_time_ns': evict,
        })
        offset += record_size

    return connections


def parse_drops(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()

    drops = []
    record_size = 24
    offset = 0
    while offset + record_size <= len(data):
        drop_type, ret_val, count, byte_count = struct.unpack_from(
            '<HxxiQQ', data, offset)
        drops.append({
            'drop_type': drop_type,
            'drop_type_name': DROP_TYPE_NAMES.get(drop_type, f'UNKNOWN_{drop_type}'),
            'return_val': ret_val,
            'count': count,
            'bytes': byte_count,
        })
        offset += record_size
    return drops


def parse_dns(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()

    events = []
    record_size = 24
    offset = 0
    while offset + record_size <= len(data):
        src_ip, dst_ip, src_port, dst_port, qid, qtype = struct.unpack_from(
            '!IIHHHH', data, offset)
        answer_count = struct.unpack_from('<H', data, offset + 16)[0]
        rcode, is_resp = struct.unpack_from('BB', data, offset + 18)
        timestamp = struct.unpack_from('<I', data, offset + 20)[0]

        events.append({
            'src_ip': int_to_ip(src_ip),
            'dst_ip': int_to_ip(dst_ip),
            'src_port': src_port,
            'dst_port': dst_port,
            'query_id': qid,
            'query_type': qtype,
            'query_type_name': QUERY_TYPE_NAMES.get(qtype, f'TYPE{qtype}'),
            'answer_count': answer_count,
            'response_code': rcode,
            'response_code_name': RCODE_NAMES.get(rcode, f'RCODE{rcode}'),
            'is_response': bool(is_resp),
            'timestamp_ns': timestamp,
        })
        offset += record_size
    return events


def parse_retransmits(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()

    events = []
    record_size = 20
    offset = 0
    while offset + record_size <= len(data):
        tcp_state = struct.unpack_from('<I', data, offset)[0]
        src_port, dst_port, src_ip, dst_ip = struct.unpack_from(
            '!HHII', data, offset + 4)
        tcp_flags, af = struct.unpack_from('BB', data, offset + 16)

        events.append({
            'src_ip': int_to_ip(src_ip),
            'dst_ip': int_to_ip(dst_ip),
            'src_port': src_port,
            'dst_port': dst_port,
            'tcp_state': tcp_state,
            'tcp_flags': tcp_flags,
            'af': af,
        })
        offset += record_size
    return events


# =====================================================================
# PCAP Analysis (pure Python, no tshark dependency)
# =====================================================================
def parse_pcap(pcap_path):
    """Parse libpcap file directly to extract DNS query names and packet
    statistics without depending on tshark output format."""
    dns_names = {}
    total_packets = 0
    timestamps = []

    with open(pcap_path, 'rb') as f:
        ghdr = f.read(24)
        if len(ghdr) < 24:
            return dns_names, {'total_packets': 0, 'capture_duration_secs': 0}

        magic = struct.unpack('<I', ghdr[:4])[0]
        if magic == 0xa1b2c3d4:
            endian = '<'
        elif magic == 0xd4c3b2a1:
            endian = '>'
        else:
            return dns_names, {'total_packets': 0, 'capture_duration_secs': 0}

        while True:
            rec_hdr = f.read(16)
            if len(rec_hdr) < 16:
                break
            ts_sec, ts_usec, caplen, _ = struct.unpack(endian + 'IIII', rec_hdr)
            timestamps.append(ts_sec + ts_usec / 1e6)
            total_packets += 1

            pkt = f.read(caplen)
            if len(pkt) < caplen:
                break

            # Need at least Ethernet (14) + min IPv4 (20) = 34 bytes
            if len(pkt) < 34:
                continue
            # Check EtherType = IPv4 (0x0800)
            if struct.unpack('!H', pkt[12:14])[0] != 0x0800:
                continue

            ihl = (pkt[14] & 0x0F) * 4
            proto = pkt[23]  # IP protocol field at offset 14+9
            if proto != 17:  # Not UDP
                continue

            udp_off = 14 + ihl
            if len(pkt) < udp_off + 8:
                continue
            dst_port = struct.unpack('!H', pkt[udp_off + 2:udp_off + 4])[0]
            if dst_port != 53:  # Not a DNS query (to port 53)
                continue

            dns_off = udp_off + 8
            if len(pkt) < dns_off + 12:
                continue
            dns_id, flags = struct.unpack('!HH', pkt[dns_off:dns_off + 4])
            if flags & 0x8000:  # QR bit set = response, skip
                continue

            # Parse DNS question name (wire format: length-prefixed labels + null)
            pos = dns_off + 12
            labels = []
            while pos < len(pkt) and pkt[pos] != 0:
                llen = pkt[pos]
                pos += 1
                if pos + llen > len(pkt):
                    break
                labels.append(pkt[pos:pos + llen].decode('ascii', errors='replace'))
                pos += llen
            if labels:
                dns_names[dns_id] = '.'.join(labels)

    if len(timestamps) >= 2:
        duration = int(max(timestamps) - min(timestamps))
    else:
        duration = 0

    pcap_stats = {
        'total_packets': total_packets,
        'capture_duration_secs': duration,
    }
    return dns_names, pcap_stats


# =====================================================================
# Correlation & Anomaly Detection
# =====================================================================
def correlate_retransmits(connections, retransmits):
    """Match retransmit events to connections by 4-tuple, update counts."""
    retx_counts = {}
    for r in retransmits:
        key = f"{r['src_ip']}:{r['src_port']}->{r['dst_ip']}:{r['dst_port']}"
        retx_counts[key] = retx_counts.get(key, 0) + 1

    for conn in connections:
        conn['retransmit_count'] = retx_counts.get(conn_key(conn), 0)


def correlate_dns(dns_events, dns_names):
    """Match DNS queries to responses by query_id, enrich with pcap names."""
    queries = {}
    responses = {}
    for evt in dns_events:
        if not evt['is_response']:
            queries[evt['query_id']] = evt
        else:
            responses[evt['query_id']] = evt

    correlations = []
    unmatched_qids = []

    for qid in sorted(queries):
        query = queries[qid]
        resp = responses.get(qid)
        corr = {
            'query_id': qid,
            'query_name': dns_names.get(qid, ''),
            'query_type': query['query_type_name'],
            'src_ip': query['src_ip'],
            'dst_ip': query['dst_ip'],
            'src_port': query['src_port'],
            'has_response': resp is not None,
            'response_code': resp['response_code_name'] if resp else None,
            'answer_count': resp['answer_count'] if resp else 0,
        }
        if resp:
            corr['latency_ns'] = resp['timestamp_ns'] - query['timestamp_ns']
        if resp is None:
            unmatched_qids.append(qid)
        correlations.append(corr)

    return correlations, unmatched_qids


def detect_anomalies(connections, retransmits, dns_events, config):
    """Detect network anomalies across all data sources using config thresholds."""
    anomalies = []

    # Read thresholds from config
    rst_threshold = config.get('rst_storm', {}).get('min_rst_total', 10)
    retx_threshold = config.get('retransmit_heavy', {}).get('min_retransmits', 10)
    asym_ratio = config.get('asymmetric_flow', {}).get('min_byte_ratio', 100)
    asym_nonzero = config.get('asymmetric_flow', {}).get('both_directions_nonzero', True)

    for conn in connections:
        key = conn_key(conn)
        if conn['proto'] == 'TCP':
            tx = conn['flags_summary']['tx']
            rx = conn['flags_summary']['rx']

            # half_open
            if tx['syn'] > 0 and rx['syn'] == 0:
                anomalies.append({
                    'type': 'half_open',
                    'connection': key,
                    'detail': f"SYN sent ({tx['syn']}x) but no SYN-ACK received",
                })

            # rst_storm
            total_rst = tx['rst'] + rx['rst']
            if total_rst > rst_threshold:
                anomalies.append({
                    'type': 'rst_storm',
                    'connection': key,
                    'detail': f"{total_rst} RST packets (tx={tx['rst']}, rx={rx['rst']})",
                })

            # fin_not_acked
            if conn['is_closing'] and tx['fin'] > 0 and rx['fin'] == 0:
                anomalies.append({
                    'type': 'fin_not_acked',
                    'connection': key,
                    'detail': 'FIN sent but not received in reverse direction',
                })

            # asymmetric_flow
            if asym_nonzero and conn['bytes_tx'] > 0 and conn['bytes_rx'] > 0:
                ratio = max(conn['bytes_tx'] / conn['bytes_rx'],
                            conn['bytes_rx'] / conn['bytes_tx'])
                if ratio > asym_ratio:
                    anomalies.append({
                        'type': 'asymmetric_flow',
                        'connection': key,
                        'detail': f"Byte ratio {ratio:.1f}:1 (tx={conn['bytes_tx']}, rx={conn['bytes_rx']})",
                    })

        # retransmit_heavy (protocol-independent check)
        if conn['retransmit_count'] > retx_threshold:
            anomalies.append({
                'type': 'retransmit_heavy',
                'connection': key,
                'detail': f"{conn['retransmit_count']} retransmissions",
            })

    # dns_no_response
    _, unmatched = correlate_dns(dns_events, {})
    for qid in unmatched:
        for evt in dns_events:
            if evt['query_id'] == qid and not evt['is_response']:
                anomalies.append({
                    'type': 'dns_no_response',
                    'connection': f"{evt['src_ip']}:{evt['src_port']}->{evt['dst_ip']}:{evt['dst_port']}",
                    'detail': f"DNS query ID 0x{qid:04x} ({evt['query_type_name']}) got no response",
                })
                break

    return anomalies


# =====================================================================
# Main
# =====================================================================
def main():
    data_dir = '/app/data'
    config_path = '/app/anomaly_config.yaml'
    pcap_path = f'{data_dir}/capture.pcap'

    # Load anomaly detection config
    config = load_config(config_path)

    # Parse all binary data sources
    connections = parse_conntrack(f'{data_dir}/conntrack_entries.bin')
    drops = parse_drops(f'{data_dir}/drop_events.bin')
    dns_events = parse_dns(f'{data_dir}/dns_events.bin')
    retransmits = parse_retransmits(f'{data_dir}/tcp_retransmits.bin')

    # Parse pcap for DNS domain names and capture statistics
    dns_names, pcap_stats = parse_pcap(pcap_path)

    # Cross-source correlation
    correlate_retransmits(connections, retransmits)
    dns_correlations, _ = correlate_dns(dns_events, dns_names)

    # Anomaly detection
    anomalies = detect_anomalies(connections, retransmits, dns_events, config)

    # Summary statistics
    anomalous_keys = set(a['connection'] for a in anomalies)
    tcp_conns = [c for c in connections if c['proto'] == 'TCP']
    udp_conns = [c for c in connections if c['proto'] == 'UDP']

    summary = {
        'total_connections': len(connections),
        'tcp_connections': len(tcp_conns),
        'udp_connections': len(udp_conns),
        'total_anomalies': len(anomalies),
        'anomaly_types': sorted(set(a['type'] for a in anomalies)),
        'total_bytes_tx': sum(c['bytes_tx'] for c in connections),
        'total_bytes_rx': sum(c['bytes_rx'] for c in connections),
        'total_packets_tx': sum(c['packets_tx'] for c in connections),
        'total_packets_rx': sum(c['packets_rx'] for c in connections),
        'total_drop_count': sum(d['count'] for d in drops),
        'total_drop_bytes': sum(d['bytes'] for d in drops),
        'total_retransmits': len(retransmits),
        'dns_queries': sum(1 for e in dns_events if not e['is_response']),
        'dns_responses': sum(1 for e in dns_events if e['is_response']),
        'connections_with_anomalies': len(anomalous_keys),
    }

    report = {
        'connections': connections,
        'drops': drops,
        'anomalies': anomalies,
        'dns_correlations': dns_correlations,
        'pcap_analysis': pcap_stats,
        'summary': summary,
    }

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Report: {len(connections)} connections, {len(anomalies)} anomalies, "
          f"{len(dns_correlations)} DNS correlations, "
          f"{pcap_stats['total_packets']} pcap packets")


if __name__ == '__main__':
    main()
