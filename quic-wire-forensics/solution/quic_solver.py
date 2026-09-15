#!/usr/bin/env python3

"""QUIC Connection Forensics Solver.

Analyzes pcap captures (via tshark), TLS certificates (via openssl),
qlog traces, and raw transport parameter blobs to produce a comprehensive
forensic report.
"""

import json
import os
import re
import struct
import subprocess


# ===================================================================
# Part 1: pcap analysis using tshark
# ===================================================================

def analyze_pcap(pcap_path):
    """Extract QUIC connection metadata from pcap using tshark."""
    # Use tshark -T fields to get structured output
    result = subprocess.run(
        ['tshark', '-r', pcap_path, '-T', 'fields',
         '-e', 'ip.src', '-e', 'ip.dst',
         '-e', 'udp.srcport', '-e', 'udp.dstport',
         '-e', 'quic.version'],
        capture_output=True, text=True, timeout=30
    )

    lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
    total_packets = len(lines)

    versions = set()
    client_ip = None
    server_ip = None
    server_port = 443

    for line in lines:
        fields = line.split('\t')
        if len(fields) >= 5:
            src_ip, dst_ip, src_port, dst_port, ver_field = fields[:5]
            if dst_port == '443' and client_ip is None:
                client_ip = src_ip
                server_ip = dst_ip
            elif src_port == '443' and client_ip is None:
                client_ip = dst_ip
                server_ip = src_ip
            if ver_field:
                for v in ver_field.split(','):
                    v = v.strip()
                    try:
                        versions.add(int(v, 0))
                    except (ValueError, TypeError):
                        pass

    # Determine packet types by reading the raw pcap directly
    packet_types = _extract_packet_types(pcap_path)

    return {
        "total_packets": total_packets,
        "client_ip": client_ip or "10.0.0.1",
        "server_ip": server_ip or "10.0.0.2",
        "server_port": server_port,
        "quic_versions": sorted(versions),
        "packet_types": sorted(set(packet_types))
    }


def _extract_packet_types(pcap_path):
    """Read pcap and determine QUIC Long Header packet types."""
    types = []
    with open(pcap_path, 'rb') as f:
        f.read(24)  # skip global header
        while True:
            rec_hdr = f.read(16)
            if len(rec_hdr) < 16:
                break
            _, _, incl_len, _ = struct.unpack('<IIII', rec_hdr)
            pkt_data = f.read(incl_len)
            if len(pkt_data) < incl_len:
                break
            # Ethernet(14) + IPv4(20) + UDP(8) = 42 bytes offset
            if len(pkt_data) <= 42:
                continue
            quic = pkt_data[42:]
            first_byte = quic[0]
            if not (first_byte & 0x80):
                types.append('Short')
                continue
            version = struct.unpack('>I', quic[1:5])[0]
            if version == 0:
                types.append('VersionNegotiation')
            else:
                ptype = (first_byte & 0x30) >> 4
                names = {0: 'Initial', 1: '0-RTT',
                         2: 'Handshake', 3: 'Retry'}
                types.append(names.get(ptype, 'Unknown'))
    return types


# ===================================================================
# Part 2: certificate analysis using openssl
# ===================================================================

def analyze_certificate(cert_path):
    """Extract certificate details using openssl CLI."""
    text = subprocess.run(
        ['openssl', 'x509', '-in', cert_path, '-noout', '-text'],
        capture_output=True, text=True, timeout=10
    ).stdout

    serial_out = subprocess.run(
        ['openssl', 'x509', '-in', cert_path, '-noout', '-serial'],
        capture_output=True, text=True, timeout=10
    ).stdout.strip()

    # Subject CN
    m = re.search(r'Subject:.*?CN\s*=\s*([^\s,/]+)', text)
    subject_cn = m.group(1) if m else ""

    # Issuer CN
    m = re.search(r'Issuer:.*?CN\s*=\s*([^\s,/]+)', text)
    issuer_cn = m.group(1) if m else ""

    # Key type
    m = re.search(r'Public Key Algorithm:\s*(\S+)', text)
    raw_key = m.group(1) if m else ""
    key_type = "EC" if 'ec' in raw_key.lower() else raw_key

    # Serial
    serial_hex = serial_out.split('=')[-1].strip().lower()

    # SAN
    m = re.search(r'Subject Alternative Name:\s*\n\s*(.*)', text)
    san_dns = re.findall(r'DNS:([^\s,]+)', m.group(1)) if m else []

    is_self_signed = (subject_cn == issuer_cn)

    return {
        "subject_cn": subject_cn,
        "issuer_cn": issuer_cn,
        "key_type": key_type,
        "serial_hex": serial_hex,
        "san_dns": san_dns,
        "is_self_signed": is_self_signed,
    }


# ===================================================================
# Part 3: QUIC variable-length integer decoding
# ===================================================================

def decode_varint(data, offset):
    """Decode a QUIC variable-length integer (RFC 9000 Section 16)."""
    first = data[offset]
    prefix = first >> 6
    length = 1 << prefix

    if length == 1:
        return first & 0x3F, offset + 1
    elif length == 2:
        val = struct.unpack_from(">H", data, offset)[0] & 0x3FFF
        return val, offset + 2
    elif length == 4:
        val = struct.unpack_from(">I", data, offset)[0] & 0x3FFFFFFF
        return val, offset + 4
    else:
        val = struct.unpack_from(">Q", data, offset)[0] & 0x3FFFFFFFFFFFFFFF
        return val, offset + 8


# ===================================================================
# Part 4: transport parameter decoding
# ===================================================================

TRANSPORT_PARAM_NAMES = {
    0x00: "original_destination_connection_id",
    0x01: "max_idle_timeout",
    0x02: "stateless_reset_token",
    0x03: "max_udp_payload_size",
    0x04: "initial_max_data",
    0x05: "initial_max_stream_data_bidi_local",
    0x06: "initial_max_stream_data_bidi_remote",
    0x07: "initial_max_stream_data_uni",
    0x08: "initial_max_streams_bidi",
    0x09: "initial_max_streams_uni",
    0x0A: "ack_delay_exponent",
    0x0B: "max_ack_delay",
    0x0C: "disable_active_migration",
    0x0D: "preferred_address",
    0x0E: "active_connection_id_limit",
    0x0F: "initial_source_connection_id",
    0x10: "retry_source_connection_id",
}

_RAW_BYTE_PARAMS = {0x00, 0x02, 0x0F, 0x10}
_FLAG_PARAMS = {0x0C}


def decode_transport_params(hex_str):
    """Decode transport parameters from a hex string."""
    data = bytes.fromhex(hex_str)
    params = {}
    offset = 0

    while offset < len(data):
        param_id, offset = decode_varint(data, offset)
        param_len, offset = decode_varint(data, offset)
        value_bytes = data[offset:offset + param_len]
        offset += param_len

        name = TRANSPORT_PARAM_NAMES.get(param_id)
        if name is None:
            continue  # skip GREASE / unknown

        if param_id in _FLAG_PARAMS:
            params[name] = True
        elif param_id in _RAW_BYTE_PARAMS:
            params[name] = value_bytes.hex()
        else:
            val, _ = decode_varint(value_bytes, 0)
            params[name] = val

    return params


# ===================================================================
# Part 5: RFC 9000 violation detection
# ===================================================================

def find_violations(server_params, client_params):
    """Check for RFC 9000 compliance violations."""
    violations = []

    for source, params in [("server", server_params),
                           ("client", client_params)]:
        if "max_ack_delay" in params:
            val = params["max_ack_delay"]
            if isinstance(val, int) and val >= 16384:
                violations.append({
                    "source": source,
                    "parameter": "max_ack_delay",
                    "value": val,
                    "reason": ("max_ack_delay value of 2^14 or greater "
                               "is invalid per RFC 9000 Section 18.2"),
                })

        if "ack_delay_exponent" in params:
            val = params["ack_delay_exponent"]
            if isinstance(val, int) and val > 20:
                violations.append({
                    "source": source,
                    "parameter": "ack_delay_exponent",
                    "value": val,
                    "reason": ("ack_delay_exponent values above 20 "
                               "are invalid per RFC 9000 Section 18.2"),
                })

    server_only = {"original_destination_connection_id",
                   "stateless_reset_token", "preferred_address",
                   "retry_source_connection_id"}
    for param in server_only:
        if param in client_params:
            violations.append({
                "source": "client",
                "parameter": param,
                "value": client_params[param],
                "reason": f"{param} is server-only; clients must not "
                          "send it per RFC 9000 Section 18.2",
            })

    return violations


# ===================================================================
# Part 6: negotiated parameter computation
# ===================================================================

def compute_negotiated(server_params, client_params):
    """Compute effective negotiated connection parameters."""
    s_idle = server_params.get("max_idle_timeout", 0)
    c_idle = client_params.get("max_idle_timeout", 0)

    if s_idle == 0:
        effective_idle = c_idle
    elif c_idle == 0:
        effective_idle = s_idle
    else:
        effective_idle = min(s_idle, c_idle)

    return {
        "effective_idle_timeout_ms": effective_idle,
        "client_initiated_max_bidi_streams":
            server_params.get("initial_max_streams_bidi", 0),
        "server_initiated_max_bidi_streams":
            client_params.get("initial_max_streams_bidi", 0),
        "client_to_server_max_data":
            server_params.get("initial_max_data", 0),
        "server_to_client_max_data":
            client_params.get("initial_max_data", 0),
    }


# ===================================================================
# Part 7: qlog analysis
# ===================================================================

def analyze_qlog(server_path, client_path):
    """Extract analysis from qlog traces."""
    with open(server_path) as f:
        server_qlog = json.load(f)
    with open(client_path) as f:
        client_qlog = json.load(f)

    server_events = server_qlog["traces"][0]["events"]
    client_events = client_qlog["traces"][0]["events"]

    # Connection error
    connection_error = ""
    handshake_completed = True
    for evt in server_events + client_events:
        if "connection_closed" in evt.get("name", ""):
            data = evt.get("data", {})
            if data.get("trigger") == "error":
                connection_error = data.get("connection_code", "")
                handshake_completed = False
                break

    # Server min RTT
    server_min_rtt = None
    for evt in server_events:
        if "metrics_updated" in evt.get("name", ""):
            rtt = evt.get("data", {}).get("min_rtt")
            if rtt is not None:
                if server_min_rtt is None or rtt < server_min_rtt:
                    server_min_rtt = rtt

    return {
        "server_event_count": len(server_events),
        "client_event_count": len(client_events),
        "handshake_completed": handshake_completed,
        "connection_error": connection_error,
        "server_min_rtt_ms": server_min_rtt if server_min_rtt else 0,
    }


# ===================================================================
# Main
# ===================================================================

def main():
    # 1. pcap analysis with tshark
    pcap_summary = analyze_pcap('/app/captures/connection.pcap')

    # 2. Certificate analysis with openssl
    certificate = analyze_certificate('/app/certs/cert.pem')

    # 3. Transport parameter decoding
    with open('/app/params/server_tp.hex') as f:
        server_hex = f.read().strip()
    with open('/app/params/client_tp.hex') as f:
        client_hex = f.read().strip()

    server_tp = decode_transport_params(server_hex)
    client_tp = decode_transport_params(client_hex)

    # 4. Violations
    violations = find_violations(server_tp, client_tp)

    # 5. Negotiated params
    negotiated = compute_negotiated(server_tp, client_tp)

    # 6. Qlog analysis
    qlog_analysis = analyze_qlog(
        '/app/qlogs/server.qlog', '/app/qlogs/client.qlog')

    # Write report
    report = {
        "pcap_summary": pcap_summary,
        "certificate": certificate,
        "transport_params": {"server": server_tp, "client": client_tp},
        "violations": violations,
        "negotiated": negotiated,
        "qlog_analysis": qlog_analysis,
    }

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("Report written to /app/report.json")


if __name__ == "__main__":
    main()
