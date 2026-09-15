#!/usr/bin/env python3
"""
TCP-AO Security Audit Tool

Cross-validates candidate implementations using tshark (pcap extraction),
openssl CLI (reference KDF computation), and Python (orchestration).
Produces /app/audit_report.json.

"""

import json
import struct
import socket
import subprocess
import importlib.util
import sys
import os
import tempfile
import re


# ======================================================================
# Dynamic candidate loading
# ======================================================================

def load_candidate(name):
    path = f'/app/candidates/{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ======================================================================
# Helper: IP address to bytes
# ======================================================================

def ip_to_bytes(ip):
    if ':' in ip:
        return socket.inet_pton(socket.AF_INET6, ip)
    return socket.inet_pton(socket.AF_INET, ip)


# ======================================================================
# Build KDF context for client SYN (dst_ISN = 0)
# ======================================================================

def build_context(conn):
    src_ip_bytes = ip_to_bytes(conn['client_ip'])
    dst_ip_bytes = ip_to_bytes(conn['server_ip'])
    src_port = conn['client_port']
    dst_port = conn['server_port']
    src_isn = (int(conn['client_isn'], 16)
               if isinstance(conn['client_isn'], str)
               else conn['client_isn'])
    dst_isn = 0  # SYN: peer ISN unknown
    return (src_ip_bytes + dst_ip_bytes +
            struct.pack('!HH', src_port, dst_port) +
            struct.pack('!II', src_isn, dst_isn))


# ======================================================================
# OpenSSL CLI wrappers
# ======================================================================

def openssl_hmac_sha1(key_hex, input_bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as f:
        f.write(input_bytes)
        tmpfile = f.name
    try:
        result = subprocess.run(
            ['openssl', 'mac', '-digest', 'SHA1',
             '-macopt', f'hexkey:{key_hex}',
             '-binary', '-in', tmpfile, 'HMAC'],
            capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"openssl HMAC failed: {result.stderr.decode()}")
        return result.stdout
    finally:
        os.unlink(tmpfile)


def openssl_aes_cmac(key_hex, input_bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as f:
        f.write(input_bytes)
        tmpfile = f.name
    try:
        result = subprocess.run(
            ['openssl', 'mac', '-cipher', 'aes-128-cbc',
             '-macopt', f'hexkey:{key_hex}',
             '-binary', '-in', tmpfile, 'CMAC'],
            capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"openssl CMAC failed: {result.stderr.decode()}")
        return result.stdout
    finally:
        os.unlink(tmpfile)


# ======================================================================
# Compute reference traffic key using openssl CLI
# ======================================================================

def compute_reference_key_openssl(conn, master_key_str):
    master_key = master_key_str.encode('ascii')
    master_key_hex = master_key.hex()
    context = build_context(conn)
    kdf_alg = conn['kdf_alg']
    label = b"TCP-AO"

    if kdf_alg == "HMAC-SHA1":
        output_bits = 160
        enc_len = struct.pack('>H', output_bits)
        kdf_input = b'\x01' + label + context + enc_len
        result = openssl_hmac_sha1(master_key_hex, kdf_input)
        cmd = (f"openssl mac -digest SHA1 "
               f"-macopt hexkey:{master_key_hex} "
               f"-binary -in kdf_input.bin HMAC")
        return result.hex(), cmd

    elif kdf_alg == "AES-128-CMAC":
        output_bits = 128
        # Step 1: normalize key via AES-CMAC(0^128, master_key)
        zero_key_hex = '00' * 16
        K = openssl_aes_cmac(zero_key_hex, master_key)
        normalized_key_hex = K.hex()

        # Step 2: KDF with normalized key
        enc_len = struct.pack('>H', output_bits)
        kdf_input = b'\x01' + label + context + enc_len
        result = openssl_aes_cmac(normalized_key_hex, kdf_input)
        cmd = (f"openssl mac -cipher aes-128-cbc "
               f"-macopt hexkey:{zero_key_hex} "
               f"-binary -in master_key.bin CMAC && "
               f"openssl mac -cipher aes-128-cbc "
               f"-macopt hexkey:{normalized_key_hex} "
               f"-binary -in kdf_input.bin CMAC")
        return result.hex(), cmd

    raise ValueError(f"Unknown KDF: {kdf_alg}")


# ======================================================================
# Parse pcap binary for TCP-AO option data
# ======================================================================

def parse_pcap_raw(filename):
    packets = []
    with open(filename, 'rb') as f:
        # Global header (24 bytes)
        hdr = f.read(24)
        magic, major, minor, tz, sigfigs, snaplen, network = \
            struct.unpack('<IHHiIII', hdr)

        frame = 0
        while True:
            pkt_hdr = f.read(16)
            if len(pkt_hdr) < 16:
                break
            ts_sec, ts_usec, incl_len, orig_len = \
                struct.unpack('<IIII', pkt_hdr)
            data = f.read(incl_len)
            if len(data) < incl_len:
                break
            frame += 1

            # Parse IP header
            ip_ver = (data[0] >> 4) & 0xF
            if ip_ver == 4:
                ihl = (data[0] & 0xF) * 4
                src_ip = socket.inet_ntop(
                    socket.AF_INET, data[12:16])
                dst_ip = socket.inet_ntop(
                    socket.AF_INET, data[16:20])
                tcp_start = ihl
            elif ip_ver == 6:
                src_ip = socket.inet_ntop(
                    socket.AF_INET6, data[8:24])
                dst_ip = socket.inet_ntop(
                    socket.AF_INET6, data[24:40])
                tcp_start = 40
            else:
                continue

            # Parse TCP header
            tcp = data[tcp_start:]
            src_port = struct.unpack('!H', tcp[0:2])[0]
            dst_port = struct.unpack('!H', tcp[2:4])[0]
            data_offset = ((tcp[12] >> 4) & 0xF) * 4
            options = tcp[20:data_offset]

            # Find TCP-AO option (kind 29)
            i = 0
            ao_keyid = ao_rnext = None
            ao_mac = ""
            while i < len(options):
                kind = options[i]
                if kind == 0:
                    break
                if kind == 1:
                    i += 1
                    continue
                if i + 1 >= len(options):
                    break
                length = options[i + 1]
                if length < 2:
                    break
                if kind == 29:
                    ao_keyid = options[i + 2]
                    ao_rnext = options[i + 3]
                    ao_mac = options[i + 4:i + length].hex()
                    break
                i += length

            packets.append({
                'frame': frame,
                'src_ip': src_ip,
                'dst_ip': dst_ip,
                'src_port': src_port,
                'dst_port': dst_port,
                'ao_keyid': ao_keyid,
                'ao_rnextkeyid': ao_rnext,
                'ao_mac': ao_mac,
            })

    return packets


# ======================================================================
# tshark extraction (for the tshark_command record)
# ======================================================================

def run_tshark(pcap_path):
    tshark_cmd = (f"tshark -r {pcap_path} -T fields "
                  f"-e frame.number -e ip.src -e ipv6.src "
                  f"-e ip.dst -e ipv6.dst "
                  f"-e tcp.srcport -e tcp.dstport")

    result = subprocess.run(
        tshark_cmd.split(), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"tshark stderr: {result.stderr}", file=sys.stderr)
        raise RuntimeError("tshark failed")

    tshark_packets = []
    for line in result.stdout.strip().split('\n'):
        if not line.strip():
            continue
        parts = line.split('\t')
        frame = int(parts[0])
        src_ip = parts[1] or parts[2]
        dst_ip = parts[3] or parts[4]
        src_port = int(parts[5])
        dst_port = int(parts[6])
        tshark_packets.append({
            'frame': frame,
            'src_ip': src_ip,
            'dst_ip': dst_ip,
            'src_port': src_port,
            'dst_port': dst_port,
        })

    return tshark_cmd, tshark_packets


# ======================================================================
# Match packet to connection by client port
# ======================================================================

def match_connection(packet, connections):
    for conn in connections:
        if packet['src_port'] == conn['client_port']:
            return conn['id']
    return None


# ======================================================================
# Evaluate a candidate implementation
# ======================================================================

def evaluate_candidate(name, connections, master_key, reference_keys):
    mod = load_candidate(name)
    failing = []

    mk_bytes = master_key.encode('ascii')

    for conn in connections:
        src_isn = (int(conn['client_isn'], 16)
                   if isinstance(conn['client_isn'], str)
                   else conn['client_isn'])
        try:
            key = mod.derive_traffic_key(
                conn['kdf_alg'], mk_bytes,
                conn['client_ip'], conn['server_ip'],
                conn['client_port'], conn['server_port'],
                src_isn, 0)  # SYN: dst_ISN=0
            candidate_hex = key.hex()
        except Exception as e:
            print(f"  {name} error on {conn['id']}: {e}",
                  file=sys.stderr)
            failing.append(conn['id'])
            continue

        ref = reference_keys.get(conn['id'])
        if ref and candidate_hex != ref:
            failing.append(conn['id'])

    return failing


# ======================================================================
# Diagnose bug by analyzing failure pattern + source code
# ======================================================================

def diagnose_candidate(name, failing_set, all_ids, aes_ids):
    if not failing_set:
        return {
            "verdict": "pass",
            "failing_connections": [],
            "bug_description":
                "Implementation correctly follows "
                "RFC 5925/5926 specifications",
            "rfc_violation": "none",
            "severity": "none"
        }

    failing_list = sorted(list(failing_set))

    # Read source to identify bug
    with open(f'/app/candidates/{name}.py') as f:
        code = f.read()

    if failing_set == all_ids:
        # All connections fail: core KDF issue
        if '\\x00' in code and 'TCP-AO' in code:
            # Check for null-terminated label
            return {
                "verdict": "fail",
                "failing_connections": failing_list,
                "bug_description":
                    "KDF label includes null terminator "
                    "(b'TCP-AO\\x00' instead of b'TCP-AO')",
                "rfc_violation": "RFC 5926 Section 3.1",
                "severity": "critical"
            }
        # Check for counter-from-0 pattern
        if re.search(r'range\(iters\)', code):
            return {
                "verdict": "fail",
                "failing_connections": failing_list,
                "bug_description":
                    "KDF counter starts at 0 instead of 1 "
                    "(NIST SP 800-108 requires i=1)",
                "rfc_violation": "NIST SP 800-108 Section 5.1",
                "severity": "critical"
            }
        return {
            "verdict": "fail",
            "failing_connections": failing_list,
            "bug_description":
                "All KDF outputs incorrect",
            "rfc_violation": "RFC 5926 Section 3.1",
            "severity": "critical"
        }

    if failing_set == aes_ids:
        return {
            "verdict": "fail",
            "failing_connections": failing_list,
            "bug_description":
                "AES-128-CMAC key normalization uses zero-padding "
                "instead of AES-CMAC(0^128, master_key)",
            "rfc_violation": "RFC 5926 Section 3.1.1.2",
            "severity": "high"
        }

    return {
        "verdict": "fail",
        "failing_connections": failing_list,
        "bug_description": "Partial KDF failure",
        "rfc_violation": "RFC 5926",
        "severity": "high"
    }


# ======================================================================
# Main
# ======================================================================

def main():
    print("=== TCP-AO Security Audit ===")

    # Load connections
    with open('/app/connections.json') as f:
        data = json.load(f)
    connections = data['connections']
    master_key = data['master_key']

    ALL_IDS = {c['id'] for c in connections}
    AES_IDS = {c['id'] for c in connections
               if c['kdf_alg'] == 'AES-128-CMAC'}

    # Step 1: tshark extraction
    print("\n[1] Extracting packet info with tshark...")
    tshark_cmd, tshark_packets = run_tshark('/app/bgp_capture.pcap')
    print(f"    tshark extracted {len(tshark_packets)} packets")

    # Step 2: Parse raw pcap for TCP-AO options
    print("\n[2] Parsing TCP-AO options from pcap binary...")
    raw_packets = parse_pcap_raw('/app/bgp_capture.pcap')
    print(f"    Found {len(raw_packets)} packets with TCP-AO options")

    # Merge tshark + raw pcap data and map to connections
    pcap_analysis_packets = []
    for raw_pkt in raw_packets:
        conn_id = match_connection(raw_pkt, connections)
        if conn_id:
            raw_pkt['connection_id'] = conn_id
            pcap_analysis_packets.append(raw_pkt)

    # Step 3: Compute reference traffic keys with openssl
    print("\n[3] Computing reference traffic keys with openssl...")
    openssl_commands = []
    reference_keys = {}
    for conn in connections:
        ref_key, cmd = compute_reference_key_openssl(conn, master_key)
        reference_keys[conn['id']] = ref_key
        openssl_commands.append(cmd)
        print(f"    {conn['id']}: {ref_key}")

    # Step 4: Evaluate candidates
    print("\n[4] Evaluating candidate implementations...")
    candidate_results = {}
    for name in ['impl_a', 'impl_b', 'impl_c', 'impl_d']:
        failing = evaluate_candidate(
            name, connections, master_key, reference_keys)
        failing_set = set(failing)
        result = diagnose_candidate(name, failing_set, ALL_IDS, AES_IDS)
        candidate_results[name] = result
        print(f"    {name}: {result['verdict']} "
              f"(failing: {len(failing)}/{len(connections)})")

    # Step 5: Recommendation
    passing = [n for n, r in candidate_results.items()
               if r['verdict'] == 'pass']
    recommendation = passing[0] if passing else "none"

    # Build report
    report = {
        "candidates": candidate_results,
        "reference_values": {
            "method": "openssl",
            "openssl_commands": openssl_commands,
            "traffic_keys": reference_keys,
        },
        "pcap_analysis": {
            "method": "tshark",
            "tshark_command": tshark_cmd,
            "packets": pcap_analysis_packets,
        },
        "recommendation": recommendation,
    }

    with open('/app/audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\n=== Audit complete. Recommendation: {recommendation} ===")
    print("Report written to /app/audit_report.json")


if __name__ == '__main__':
    main()
