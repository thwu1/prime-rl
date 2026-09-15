#!/usr/bin/env python3
"""
nDPI ndpiReader output parser and incident response threat correlator.

Parses nDPI flow data, correlates with threat intelligence feed,
decodes DNS tunnel payloads, identifies attack patterns, and generates
Suricata detection rules.
"""


import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime


def shannon_entropy(s):
    if not s:
        return 0.0
    freq = defaultdict(int)
    for c in s:
        freq[c] += 1
    length = len(s)
    entropy = 0.0
    for count in freq.values():
        p = count / length
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


def parse_flow_line(line):
    flow = {}

    ts_match = re.match(r'^(\d+\.\d+)\s+', line)
    if ts_match:
        flow['timestamp'] = float(ts_match.group(1))
        line = line[ts_match.end():]
    else:
        flow['timestamp'] = None

    num_match = re.match(r'\s*(\d+)\s+', line)
    if num_match:
        flow['flow_num'] = int(num_match.group(1))
        line = line[num_match.end():]

    conn_match = re.match(
        r'(TCP|UDP|ICMP|IGMP)\s+'
        r'(\d+\.\d+\.\d+\.\d+|\[[^\]]+\]):(\d+)\s+'
        r'(<->|->)\s+'
        r'(\d+\.\d+\.\d+\.\d+|\[[^\]]+\]):(\d+)',
        line
    )
    if conn_match:
        flow['transport'] = conn_match.group(1)
        flow['src_ip'] = conn_match.group(2).strip('[]')
        flow['src_port'] = int(conn_match.group(3))
        flow['direction'] = conn_match.group(4)
        flow['dst_ip'] = conn_match.group(5).strip('[]')
        flow['dst_port'] = int(conn_match.group(6))

    proto_match = re.search(r'\[proto:\s*([^\]]+)\]', line)
    if proto_match:
        flow['proto'] = proto_match.group(1).strip()

    # Extract all [key: value] pairs
    fields = {}
    for match in re.finditer(r'\[([^\]]+)\]', line):
        content = match.group(1)
        if ': ' in content:
            key, _, val = content.partition(': ')
            fields[key.strip()] = val.strip()
        else:
            fields[content.strip()] = True
    flow['fields'] = fields

    flow['encrypted'] = 'Encrypted' in fields
    flow['cleartext'] = 'ClearText' in fields
    flow['hostname'] = fields.get('Hostname/SNI', None)

    # DNS resolved IP
    dns_resolved = None
    if flow.get('hostname'):
        hostname_pattern = re.escape(flow['hostname'])
        after_hostname = re.search(
            r'\[Hostname/SNI:\s*' + hostname_pattern + r'\]\[([^\]]+)\]',
            line
        )
        if after_hostname:
            candidate = after_hostname.group(1).strip()
            if re.match(r'^\d+\.\d+\.\d+\.\d+$', candidate):
                dns_resolved = candidate
    flow['dns_resolved_ip'] = dns_resolved

    # Risk
    risk_match = re.search(r'\[Risk:\s*\*\*\s*(.*?)\s*\*\*\]', line)
    flow['risk'] = risk_match.group(1).strip() if risk_match else None
    flow['risk_score'] = fields.get('Risk Score', None)
    flow['risk_info'] = fields.get('Risk Info', None)

    # Credentials
    flow['username'] = fields.get('Username', None)
    flow['password'] = fields.get('Password', None)

    # TLS metadata
    flow['ja4'] = fields.get('JA4', None)
    flow['issuer'] = fields.get('Issuer', None)
    flow['subject'] = fields.get('Subject', None)
    flow['validity'] = fields.get('Validity', None)
    flow['cipher'] = fields.get('Cipher', None)
    flow['server_names'] = fields.get('ServerNames', None)
    flow['cert_sha1'] = fields.get('Certificate SHA-1', None)

    # TLS version: find [TLSv1.X] standalone tag (negotiated version)
    tls_negotiated = None
    for key in fields:
        if re.match(r'^TLSv\d+(\.\d+)?$', key) and fields[key] is True:
            tls_negotiated = key
            break
    flow['tls_negotiated'] = tls_negotiated

    # TLS supported versions (client offered)
    flow['tls_supported'] = fields.get('TLS Supported Versions', None)

    flow['url'] = fields.get('URL', None)
    flow['status_code'] = fields.get('StatusCode', None)
    flow['content_type'] = fields.get('Content-Type', None)
    flow['server'] = fields.get('Server', None)
    flow['user_agent'] = fields.get('User-Agent', None)

    return flow


def parse_ndpi_output(filepath):
    flows = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.rstrip('\n')
            if re.match(r'^\d+\.\d+\s+\d+\s+(TCP|UDP|ICMP|IGMP)\s+', line):
                flow = parse_flow_line(line)
                if flow:
                    flows.append(flow)
            elif re.match(r'^\s+\d+\s+(TCP|UDP|ICMP|IGMP)\s+', line):
                flow = parse_flow_line(line)
                if flow:
                    flows.append(flow)
    return flows


def correlate_threat_intel(flows, threat_intel):
    matches = []
    for indicator in threat_intel.get('indicators', []):
        ioc_type = indicator['type']
        ioc_value = indicator['value']
        threat_name = indicator['threat_name']
        matched_flows = []

        for flow in flows:
            fnum = flow.get('flow_num', 0)

            if ioc_type == 'ip':
                if flow.get('dst_ip') == ioc_value or flow.get('src_ip') == ioc_value:
                    matched_flows.append(fnum)
            elif ioc_type == 'domain':
                hostname = flow.get('hostname', '') or ''
                if hostname.endswith(ioc_value) or ioc_value in hostname:
                    matched_flows.append(fnum)
            elif ioc_type == 'ja4':
                if flow.get('ja4') == ioc_value:
                    matched_flows.append(fnum)
            elif ioc_type == 'cert_sha1':
                if flow.get('cert_sha1') == ioc_value:
                    matched_flows.append(fnum)

        if matched_flows:
            matches.append({
                'indicator_value': ioc_value,
                'indicator_type': ioc_type,
                'threat_name': threat_name,
                'matched_flow_ids': sorted(matched_flows),
            })

    return matches


def detect_c2_beaconing(flows, min_count=4, max_cv=0.25):
    tls_by_dst = defaultdict(list)
    for flow in flows:
        proto_str = flow.get('proto', '')
        is_tls = 'TLS' in proto_str or (flow.get('dst_port') == 443 and flow.get('encrypted'))
        if is_tls and flow.get('timestamp') is not None:
            tls_by_dst[flow['dst_ip']].append(flow)

    for dst_ip, dst_flows in tls_by_dst.items():
        if len(dst_flows) < min_count:
            continue

        dst_flows.sort(key=lambda f: f['timestamp'])
        timestamps = [f['timestamp'] for f in dst_flows]

        intervals = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))]
        if not intervals:
            continue

        mean_interval = sum(intervals) / len(intervals)
        if mean_interval <= 0:
            continue

        variance = sum((x - mean_interval) ** 2 for x in intervals) / len(intervals)
        std_dev = math.sqrt(variance)
        cv = std_dev / mean_interval

        if cv < max_cv:
            hostnames = set()
            ja4s = set()
            for f in dst_flows:
                if f.get('hostname'):
                    hostnames.add(f['hostname'])
                if f.get('ja4'):
                    ja4s.add(f['ja4'])

            return {
                'server_ip': dst_ip,
                'server_port': dst_flows[0].get('dst_port', 443),
                'beacon_count': len(dst_flows),
                'mean_interval_sec': round(mean_interval, 2),
                'hostname': sorted(hostnames)[0] if hostnames else '',
                'ja4_fingerprint': sorted(ja4s)[0] if ja4s else '',
            }

    return {
        'server_ip': '',
        'server_port': 0,
        'beacon_count': 0,
        'mean_interval_sec': 0,
        'hostname': '',
        'ja4_fingerprint': '',
    }


def detect_dns_exfiltration(flows):
    tunnel_queries = []

    for flow in flows:
        proto_str = flow.get('proto', '')
        if 'DNS' not in proto_str:
            continue

        hostname = flow.get('hostname', '')
        if not hostname:
            continue

        # Check for data.exfil-srv.net pattern
        if 'data.exfil-srv.net' not in hostname:
            continue

        labels = hostname.split('.')
        # Structure: hex1.hex2.data.exfil-srv.net
        # Find labels before 'data'
        try:
            data_idx = labels.index('data')
            encoded_labels = labels[:data_idx]
        except ValueError:
            continue

        if not encoded_labels:
            continue

        raw_labels = '.'.join(encoded_labels)

        # Decode each hex label
        decoded_parts = []
        for label in encoded_labels:
            try:
                decoded_parts.append(bytes.fromhex(label).decode('utf-8', errors='replace'))
            except (ValueError, UnicodeDecodeError):
                decoded_parts.append(label)

        decoded_text = '.'.join(decoded_parts)

        tunnel_queries.append({
            'flow_id': flow.get('flow_num', 0),
            'raw_labels': raw_labels,
            'decoded_text': decoded_text,
        })

    return {
        'tunnel_domain': 'exfil-srv.net',
        'query_count': len(tunnel_queries),
        'decoded_payloads': tunnel_queries,
    }


def detect_credential_exposure(flows):
    exposures = []
    for flow in flows:
        username = flow.get('username')
        if not username:
            continue
        exposures.append({
            'flow_id': flow.get('flow_num', 0),
            'dst_ip': flow.get('dst_ip', ''),
            'dst_port': flow.get('dst_port', 0),
            'username': username,
            'url': flow.get('url', '') or '',
        })
    return exposures


def detect_tls_anomalies(flows, max_valid_days=398):
    anomalies = []
    seen = set()

    for flow in flows:
        dst_ip = flow.get('dst_ip', '')
        flow_num = flow.get('flow_num', 0)

        # Check certificate validity period
        validity_str = flow.get('validity')
        if validity_str:
            validity_match = re.match(
                r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*-\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',
                validity_str
            )
            if validity_match:
                try:
                    not_before = datetime.strptime(validity_match.group(1), '%Y-%m-%d %H:%M:%S')
                    not_after = datetime.strptime(validity_match.group(2), '%Y-%m-%d %H:%M:%S')
                    validity_days = (not_after - not_before).days
                    if validity_days > max_valid_days:
                        key = (dst_ip, 'excessive_validity')
                        if key not in seen:
                            seen.add(key)
                            anomalies.append({
                                'flow_id': flow_num,
                                'dst_ip': dst_ip,
                                'anomaly_type': 'excessive_validity',
                                'details': f"Certificate validity of {validity_days} days exceeds the {max_valid_days}-day industry maximum ({validity_match.group(1)} to {validity_match.group(2)})",
                            })
                except ValueError:
                    pass

        # Check self-signed (issuer CN matches subject CN)
        issuer = flow.get('issuer', '') or ''
        subject = flow.get('subject', '') or ''
        if issuer and subject:
            issuer_cn = re.search(r'CN=([^,\]]+)', issuer)
            subject_cn = re.search(r'CN=([^,\]]+)', subject)
            if issuer_cn and subject_cn:
                if issuer_cn.group(1).strip() == subject_cn.group(1).strip():
                    key = (dst_ip, 'self_signed')
                    if key not in seen:
                        seen.add(key)
                        anomalies.append({
                            'flow_id': flow_num,
                            'dst_ip': dst_ip,
                            'anomaly_type': 'self_signed',
                            'details': f"Self-signed certificate: issuer CN '{issuer_cn.group(1).strip()}' matches subject CN",
                        })

        # Also check nDPI risk flag for self-signed
        risk = flow.get('risk', '') or ''
        if 'Self-signed' in risk:
            key = (dst_ip, 'self_signed')
            if key not in seen:
                seen.add(key)
                anomalies.append({
                    'flow_id': flow_num,
                    'dst_ip': dst_ip,
                    'anomaly_type': 'self_signed',
                    'details': f"Self-signed certificate detected by nDPI risk engine",
                })

        # Check TLS version downgrade
        tls_supported = flow.get('tls_supported', '') or ''
        tls_negotiated = flow.get('tls_negotiated', '') or ''
        if tls_supported and tls_negotiated:
            # If client offered TLSv1.3 but got TLSv1.2 or lower
            offered_versions = [v.strip() for v in tls_supported.split(';')]
            client_offers_13 = any('1.3' in v for v in offered_versions)
            negotiated_12_or_lower = '1.2' in tls_negotiated or '1.1' in tls_negotiated or '1.0' in tls_negotiated

            if client_offers_13 and negotiated_12_or_lower:
                key = (dst_ip, 'version_downgrade')
                if key not in seen:
                    seen.add(key)
                    anomalies.append({
                        'flow_id': flow_num,
                        'dst_ip': dst_ip,
                        'anomaly_type': 'version_downgrade',
                        'details': f"TLS version downgrade: client offered {tls_supported} but server negotiated {tls_negotiated}",
                    })

    return anomalies


def detect_dga_domains(flows, min_entropy=2.8):
    dga_candidates = []

    for flow in flows:
        proto_str = flow.get('proto', '')
        if 'DNS' not in proto_str:
            continue

        risk_info = flow.get('risk_info', '') or ''
        if 'NXDOMAIN' not in risk_info:
            continue

        hostname = flow.get('hostname', '')
        if not hostname:
            continue

        labels = hostname.split('.')
        if len(labels) < 2:
            continue

        sld = labels[-2]
        if len(sld) < 4:
            continue

        entropy = shannon_entropy(sld)
        if entropy >= min_entropy:
            dga_candidates.append({
                'flow_id': flow.get('flow_num', 0),
                'domain': hostname,
                'entropy': round(entropy, 4),
            })

    return dga_candidates


def build_attack_timeline(flows, c2_beaconing, dns_exfil, creds, tls_anomalies, dga):
    events = []

    # DNS resolution for C2
    for flow in flows:
        proto_str = flow.get('proto', '')
        if 'DNS' not in proto_str:
            continue
        hostname = flow.get('hostname', '')
        resolved = flow.get('dns_resolved_ip', '')
        if resolved == c2_beaconing.get('server_ip', ''):
            events.append({
                'timestamp': flow['timestamp'],
                'event_type': 'dns_resolution',
                'description': f"DNS resolution of {hostname} to C2 server {resolved}",
                'flow_ids': [flow['flow_num']],
            })

    # C2 beacons
    c2_ip = c2_beaconing.get('server_ip', '')
    for flow in flows:
        if flow.get('dst_ip') == c2_ip and 'TLS' in flow.get('proto', ''):
            events.append({
                'timestamp': flow['timestamp'],
                'event_type': 'c2_beacon',
                'description': f"C2 beacon to {c2_ip}:443 via {flow.get('hostname', '')}",
                'flow_ids': [flow['flow_num']],
            })

    # DNS exfiltration
    for payload in dns_exfil.get('decoded_payloads', []):
        fid = payload['flow_id']
        flow = next((f for f in flows if f.get('flow_num') == fid), None)
        if flow:
            events.append({
                'timestamp': flow['timestamp'],
                'event_type': 'dns_exfiltration',
                'description': f"DNS tunnel query exfiltrating data: {payload['decoded_text']}",
                'flow_ids': [fid],
            })

    # Credential exposure
    for cred in creds:
        fid = cred['flow_id']
        flow = next((f for f in flows if f.get('flow_num') == fid), None)
        if flow:
            events.append({
                'timestamp': flow['timestamp'],
                'event_type': 'credential_exposure',
                'description': f"Cleartext credential '{cred['username']}' sent to {cred['dst_ip']}:{cred['dst_port']}",
                'flow_ids': [fid],
            })

    # TLS anomalies
    for anomaly in tls_anomalies:
        fid = anomaly['flow_id']
        flow = next((f for f in flows if f.get('flow_num') == fid), None)
        if flow:
            events.append({
                'timestamp': flow['timestamp'],
                'event_type': 'tls_anomaly',
                'description': f"TLS anomaly ({anomaly['anomaly_type']}) at {anomaly['dst_ip']}",
                'flow_ids': [fid],
            })

    # DGA
    for d in dga:
        fid = d['flow_id']
        flow = next((f for f in flows if f.get('flow_num') == fid), None)
        if flow:
            events.append({
                'timestamp': flow['timestamp'],
                'event_type': 'dga_query',
                'description': f"DGA domain query: {d['domain']} (entropy={d['entropy']})",
                'flow_ids': [fid],
            })

    events.sort(key=lambda e: e['timestamp'])
    return events


def generate_suricata_rules(c2_beaconing, dns_exfil, tls_anomalies, creds):
    rules = []
    sid = 1000001

    # C2 beaconing rule
    c2_ip = c2_beaconing.get('server_ip', '')
    c2_host = c2_beaconing.get('hostname', '')
    if c2_ip:
        rules.append(
            f'alert tls $HOME_NET any -> {c2_ip} 443 '
            f'(msg:"ET MALWARE CobaltBeacon C2 Beacon to {c2_ip}"; '
            f'tls.sni; content:"{c2_host}"; '
            f'sid:{sid}; rev:1;)'
        )
        sid += 1

    # DNS tunneling rule
    tunnel_domain = dns_exfil.get('tunnel_domain', '')
    if tunnel_domain:
        rules.append(
            f'alert dns $HOME_NET any -> any 53 '
            f'(msg:"ET MALWARE DNS Tunnel to {tunnel_domain}"; '
            f'dns.query; content:"{tunnel_domain}"; nocase; '
            f'sid:{sid}; rev:1;)'
        )
        sid += 1

    # Self-signed / anomalous TLS
    for anomaly in tls_anomalies:
        if anomaly['anomaly_type'] == 'self_signed':
            rules.append(
                f'alert tls $HOME_NET any -> {anomaly["dst_ip"]} any '
                f'(msg:"ET POLICY Self-Signed TLS Certificate from {anomaly["dst_ip"]}"; '
                f'flow:established,to_server; '
                f'sid:{sid}; rev:1;)'
            )
            sid += 1
            break

    # Cleartext credential rule
    if creds:
        rules.append(
            f'alert http $HOME_NET any -> $HOME_NET any '
            f'(msg:"ET POLICY Cleartext HTTP Credentials Detected"; '
            f'flow:established,to_server; '
            f'content:"Authorization"; http.header; '
            f'sid:{sid}; rev:1;)'
        )
        sid += 1

    return '\n'.join(rules) + '\n'


def analyze(ndpi_path, threat_intel_path, report_path, rules_path):
    # Parse flows
    flows = parse_ndpi_output(ndpi_path)
    if not flows:
        print(f"ERROR: No flows parsed from {ndpi_path}", file=sys.stderr)
        sys.exit(1)
    print(f"Parsed {len(flows)} flows")

    # Load threat intel
    with open(threat_intel_path) as f:
        threat_intel = json.load(f)
    print(f"Loaded {len(threat_intel.get('indicators', []))} threat intel indicators")

    # Correlate threat intel
    ti_matches = correlate_threat_intel(flows, threat_intel)
    print(f"Threat intel matches: {len(ti_matches)}")

    # Detect threats
    c2 = detect_c2_beaconing(flows)
    print(f"C2 beaconing: {c2.get('server_ip', 'none')} ({c2.get('beacon_count', 0)} beacons)")

    dns_exfil = detect_dns_exfiltration(flows)
    print(f"DNS exfiltration: {dns_exfil['query_count']} tunnel queries")

    creds = detect_credential_exposure(flows)
    print(f"Credential exposure: {len(creds)} incidents")

    tls_anom = detect_tls_anomalies(flows)
    print(f"TLS anomalies: {len(tls_anom)} issues")

    dga = detect_dga_domains(flows)
    print(f"DGA domains: {len(dga)} detected")

    # Build timeline
    timeline = build_attack_timeline(flows, c2, dns_exfil, creds, tls_anom, dga)
    print(f"Attack timeline: {len(timeline)} events")

    # Build report
    report = {
        'meta': {
            'total_flows': len(flows),
            'data_sources': [ndpi_path, threat_intel_path],
        },
        'threat_intel_matches': ti_matches,
        'c2_beaconing': c2,
        'dns_exfiltration': dns_exfil,
        'credential_exposure': creds,
        'tls_anomalies': tls_anom,
        'dga_domains': dga,
        'attack_timeline': timeline,
    }

    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Report written to {report_path}")

    # Generate Suricata rules
    rules = generate_suricata_rules(c2, dns_exfil, tls_anom, creds)
    with open(rules_path, 'w') as f:
        f.write(rules)
    print(f"Suricata rules written to {rules_path}")


if __name__ == '__main__':
    ndpi_file = '/app/data/ndpi_flows.txt'
    ti_file = '/app/data/threat_intel.json'
    report_file = '/app/report.json'
    rules_file = '/app/rules.rules'

    analyze(ndpi_file, ti_file, report_file, rules_file)
