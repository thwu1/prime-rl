#!/usr/bin/env python3
"""
TCP-AO Packet Forensics Auditor

Parses raw IP packets, implements KDF and MAC algorithms per RFC 5925/5926,
determines algorithm suites by trial, validates MACs, writes pcap and audit report.
"""

import json
import struct
import hmac
import hashlib
import socket
import subprocess
import sys
import os

sys.path.insert(0, '/app')
from aes_cmac import aes_128_cmac


# =============================================================================
# Packet Parsing
# =============================================================================

def parse_packet(hex_str):
    """Parse a hex-encoded raw IP packet into structured fields."""
    raw = bytes.fromhex(hex_str.strip())
    pkt = {}
    pkt['raw'] = raw

    ip_version = (raw[0] >> 4) & 0x0F
    pkt['ip_version'] = ip_version

    if ip_version == 4:
        ip_hdr_len = (raw[0] & 0x0F) * 4
        pkt['src_addr'] = socket.inet_ntoa(raw[12:16])
        pkt['dst_addr'] = socket.inet_ntoa(raw[16:20])
        pkt['ip_hdr_len'] = ip_hdr_len
    elif ip_version == 6:
        pkt['src_addr'] = socket.inet_ntop(socket.AF_INET6, raw[8:24])
        pkt['dst_addr'] = socket.inet_ntop(socket.AF_INET6, raw[24:40])
        pkt['ip_hdr_len'] = 40
    else:
        raise ValueError(f"Unknown IP version: {ip_version}")

    tcp_start = pkt['ip_hdr_len']
    tcp = raw[tcp_start:]

    pkt['src_port'] = struct.unpack('!H', tcp[0:2])[0]
    pkt['dst_port'] = struct.unpack('!H', tcp[2:4])[0]
    pkt['seq_num'] = struct.unpack('!I', tcp[4:8])[0]
    pkt['ack_num'] = struct.unpack('!I', tcp[8:12])[0]
    pkt['tcp_data_offset'] = ((tcp[12] >> 4) & 0x0F) * 4
    pkt['tcp_flags'] = tcp[13]

    # Determine segment type
    syn = bool(pkt['tcp_flags'] & 0x02)
    ack = bool(pkt['tcp_flags'] & 0x10)
    if syn and not ack:
        pkt['seg_type'] = 'SYN'
    elif syn and ack:
        pkt['seg_type'] = 'SYN-ACK'
    else:
        pkt['seg_type'] = 'DATA'

    # Find TCP-AO option (kind=29)
    offset = 20
    tcp_hdr_len = pkt['tcp_data_offset']
    while offset < tcp_hdr_len:
        kind = tcp[offset]
        if kind == 0:
            break
        if kind == 1:
            offset += 1
            continue
        if offset + 1 >= tcp_hdr_len:
            break
        opt_len = tcp[offset + 1]
        if opt_len < 2:
            break
        if kind == 29:
            pkt['ao_offset'] = offset  # relative to TCP start
            pkt['ao_len'] = opt_len
            pkt['ao_keyid'] = tcp[offset + 2]
            pkt['ao_rnextkeyid'] = tcp[offset + 3]
            pkt['ao_mac'] = bytes(tcp[offset + 4: offset + opt_len])
            break
        offset += opt_len

    return pkt


def normalize_5tuple(pkt):
    """Create a canonical 5-tuple key for session grouping."""
    addrs = sorted([pkt['src_addr'], pkt['dst_addr']])
    ports = sorted([pkt['src_port'], pkt['dst_port']])
    return (addrs[0], addrs[1], ports[0], ports[1], pkt['ip_version'])


def identify_direction(pkt, client_port):
    """Determine if packet is client->server or server->client."""
    if pkt['src_port'] == client_port:
        return 'client'
    else:
        return 'server'


# =============================================================================
# KDF Implementation (RFC 5926)
# =============================================================================

def build_context(src_addr, dst_addr, src_port, dst_port,
                  src_isn, dst_isn, ip_version):
    """Build KDF context per RFC 5925 Section 5.2."""
    if ip_version == 4:
        addr_bytes = socket.inet_aton(src_addr) + socket.inet_aton(dst_addr)
    else:
        addr_bytes = (socket.inet_pton(socket.AF_INET6, src_addr) +
                      socket.inet_pton(socket.AF_INET6, dst_addr))
    return (addr_bytes +
            struct.pack('!HH', src_port, dst_port) +
            struct.pack('!II', src_isn, dst_isn))


def kdf_hmac_sha1(master_key, context, output_length_bits=160):
    """KDF_HMAC_SHA1 per RFC 5926 Section 3.1.1.1."""
    label = b"TCP-AO"
    result = b""
    prf_output_bits = 160
    num_blocks = (output_length_bits + prf_output_bits - 1) // prf_output_bits

    for i in range(1, num_blocks + 1):
        input_block = (
            struct.pack('B', i) +
            label +
            context +
            struct.pack('!H', output_length_bits)
        )
        block = hmac.new(master_key, input_block, hashlib.sha1).digest()
        result += block

    return result[:output_length_bits // 8]


def kdf_aes_128_cmac(master_key, context, output_length_bits=128):
    """KDF_AES_128_CMAC per RFC 5926 Section 3.1.1.2."""
    # Key normalization per RFC 4615
    if len(master_key) == 16:
        derived_key = master_key
    else:
        derived_key = aes_128_cmac(b'\x00' * 16, master_key)

    label = b"TCP-AO"
    result = b""
    prf_output_bits = 128
    num_blocks = (output_length_bits + prf_output_bits - 1) // prf_output_bits

    for i in range(1, num_blocks + 1):
        input_block = (
            struct.pack('B', i) +
            label +
            context +
            struct.pack('!H', output_length_bits)
        )
        block = aes_128_cmac(derived_key, input_block)
        result += block

    return result[:output_length_bits // 8]


def derive_traffic_key(master_key, kdf_alg, src_addr, dst_addr,
                       src_port, dst_port, src_isn, dst_isn, ip_version):
    """Derive a TCP-AO traffic key."""
    context = build_context(src_addr, dst_addr, src_port, dst_port,
                            src_isn, dst_isn, ip_version)
    if kdf_alg == "HMAC-SHA1":
        return kdf_hmac_sha1(master_key, context, 160)
    elif kdf_alg == "AES-128-CMAC":
        return kdf_aes_128_cmac(master_key, context, 128)
    else:
        raise ValueError(f"Unknown KDF: {kdf_alg}")


# =============================================================================
# MAC Computation (RFC 5925 Section 5.1)
# =============================================================================

def _build_ipv4_pseudoheader(packet):
    """Build IPv4 TCP pseudoheader."""
    src_ip = packet[12:16]
    dst_ip = packet[16:20]
    protocol = packet[9]
    ip_hdr_len = (packet[0] & 0x0F) * 4
    total_len = struct.unpack('!H', packet[2:4])[0]
    tcp_length = total_len - ip_hdr_len
    return (src_ip + dst_ip + b'\x00' + bytes([protocol]) +
            struct.pack('!H', tcp_length)), ip_hdr_len


def _build_ipv6_pseudoheader(packet):
    """Build IPv6 TCP pseudoheader."""
    src_ip = packet[8:24]
    dst_ip = packet[24:40]
    payload_length = struct.unpack('!H', packet[4:6])[0]
    next_header = packet[6]
    return (src_ip + dst_ip + struct.pack('!I', payload_length) +
            b'\x00\x00\x00' + bytes([next_header])), 40


def compute_tcp_ao_mac(traffic_key, packet_bytes, sne, covers_options, mac_alg):
    """Compute TCP-AO MAC per RFC 5925 Section 5.1."""
    packet = bytearray(packet_bytes)
    ip_version = (packet[0] >> 4) & 0x0F

    if ip_version == 4:
        pseudoheader, ip_hdr_len = _build_ipv4_pseudoheader(packet)
    else:
        pseudoheader, ip_hdr_len = _build_ipv6_pseudoheader(packet)

    tcp = bytearray(packet[ip_hdr_len:])
    tcp_header_len = ((tcp[12] >> 4) & 0x0F) * 4

    # Find TCP-AO option
    ao_offset = None
    ao_len = None
    offset = 20
    while offset < tcp_header_len:
        kind = tcp[offset]
        if kind == 0:
            break
        if kind == 1:
            offset += 1
            continue
        if offset + 1 >= tcp_header_len:
            break
        opt_len = tcp[offset + 1]
        if opt_len < 2:
            break
        if kind == 29:
            ao_offset = offset
            ao_len = opt_len
            break
        offset += opt_len

    if ao_offset is None:
        raise ValueError("TCP-AO option not found")

    # Zero MAC field in TCP-AO option
    mac_field_offset = ao_offset + 4
    mac_field_len = ao_len - 4
    for idx in range(mac_field_offset, mac_field_offset + mac_field_len):
        tcp[idx] = 0x00

    # Zero TCP checksum
    tcp[16:18] = b'\x00\x00'

    # Build MAC input
    sne_bytes = struct.pack('!I', sne)

    if covers_options:
        tcp_header_bytes = bytes(tcp[:tcp_header_len])
    else:
        # Omits options: fixed header + TCP-AO option only
        tcp_header_bytes = bytes(tcp[:20]) + bytes(tcp[ao_offset:ao_offset + ao_len])

    tcp_payload = bytes(tcp[tcp_header_len:])
    message = sne_bytes + pseudoheader + tcp_header_bytes + tcp_payload

    if mac_alg == "HMAC-SHA-1-96":
        full_mac = hmac.new(traffic_key, message, hashlib.sha1).digest()
        return full_mac[:12]
    elif mac_alg == "AES-128-CMAC-96":
        full_mac = aes_128_cmac(traffic_key, message)
        return full_mac[:12]
    else:
        raise ValueError(f"Unknown MAC alg: {mac_alg}")


# =============================================================================
# PCAP Writer
# =============================================================================

def write_pcap(packets_raw, filename):
    """Write raw IP packets to a pcap file with LINKTYPE_RAW."""
    with open(filename, 'wb') as f:
        # Global header
        f.write(struct.pack('<I', 0xa1b2c3d4))  # magic
        f.write(struct.pack('<H', 2))  # version major
        f.write(struct.pack('<H', 4))  # version minor
        f.write(struct.pack('<i', 0))  # thiszone
        f.write(struct.pack('<I', 0))  # sigfigs
        f.write(struct.pack('<I', 65535))  # snaplen
        f.write(struct.pack('<I', 101))  # LINKTYPE_RAW

        # Packet records
        for idx, pkt_bytes in enumerate(packets_raw):
            ts_sec = 1000000 + idx
            ts_usec = 0
            f.write(struct.pack('<I', ts_sec))
            f.write(struct.pack('<I', ts_usec))
            f.write(struct.pack('<I', len(pkt_bytes)))
            f.write(struct.pack('<I', len(pkt_bytes)))
            f.write(pkt_bytes)


# =============================================================================
# Main Pipeline
# =============================================================================

def main():
    # Load config
    with open('/app/config.json') as f:
        config = json.load(f)
    master_key = config['master_key_ascii'].encode('ascii')
    client_keyid = config['client_keyid']
    server_keyid = config['server_keyid']

    # Load and parse packets
    with open('/app/packet_dump.txt') as f:
        hex_lines = [line.strip() for line in f if line.strip()]

    packets = [parse_packet(h) for h in hex_lines]

    # Group by session
    sessions = {}
    for pkt in packets:
        key = normalize_5tuple(pkt)
        if key not in sessions:
            sessions[key] = []
        sessions[key].append(pkt)

    # Process each session
    audit_sessions = []
    all_raw = []

    for session_key, pkts in sessions.items():
        # Find SYN and SYN-ACK
        syn_pkt = None
        synack_pkt = None
        for p in pkts:
            if p['seg_type'] == 'SYN':
                syn_pkt = p
            elif p['seg_type'] == 'SYN-ACK':
                synack_pkt = p

        if syn_pkt is None:
            continue

        # Determine client/server
        # Client sends SYN, so client_addr = syn src, client_port = syn src_port
        client_addr = syn_pkt['src_addr']
        server_addr = syn_pkt['dst_addr']
        client_port = syn_pkt['src_port']
        server_port = syn_pkt['dst_port']
        ip_version = syn_pkt['ip_version']
        client_isn = syn_pkt['seq_num']

        server_isn = 0
        if synack_pkt:
            server_isn = synack_pkt['seq_num']

        # Determine algorithm suite by trial on SYN packet
        found_alg = None
        found_covers = None

        for kdf_alg, mac_alg in [("HMAC-SHA1", "HMAC-SHA-1-96"),
                                  ("AES-128-CMAC", "AES-128-CMAC-96")]:
            for covers in [True, False]:
                try:
                    # Derive SYN traffic key
                    tk = derive_traffic_key(
                        master_key, kdf_alg,
                        client_addr, server_addr,
                        client_port, server_port,
                        client_isn, 0,  # dst_ISN=0 for SYN
                        ip_version
                    )
                    computed_mac = compute_tcp_ao_mac(
                        tk, syn_pkt['raw'], 0, covers, mac_alg
                    )
                    if computed_mac == syn_pkt['ao_mac']:
                        found_alg = kdf_alg
                        found_covers = covers
                        break
                except Exception:
                    continue
            if found_alg:
                break

        if not found_alg:
            continue

        mac_alg = ("HMAC-SHA-1-96" if found_alg == "HMAC-SHA1"
                   else "AES-128-CMAC-96")

        # Derive all traffic keys for this session
        client_syn_key = derive_traffic_key(
            master_key, found_alg,
            client_addr, server_addr,
            client_port, server_port,
            client_isn, 0,
            ip_version
        )

        server_synack_key = None
        if server_isn:
            server_synack_key = derive_traffic_key(
                master_key, found_alg,
                server_addr, client_addr,
                server_port, client_port,
                server_isn, client_isn,
                ip_version
            )

        # Validate MACs for all packets in this session
        pkt_results = []
        for p in pkts:
            direction = identify_direction(p, client_port)
            if p['seg_type'] == 'SYN':
                tk = client_syn_key
            elif p['seg_type'] == 'SYN-ACK':
                tk = server_synack_key
            else:
                if direction == 'client':
                    tk = derive_traffic_key(
                        master_key, found_alg,
                        client_addr, server_addr,
                        client_port, server_port,
                        client_isn, server_isn,
                        ip_version
                    )
                else:
                    tk = server_synack_key

            if tk is None:
                continue

            computed = compute_tcp_ao_mac(tk, p['raw'], 0, found_covers, mac_alg)
            mac_valid = (computed == p['ao_mac'])

            pkt_results.append({
                "type": p['seg_type'],
                "direction": direction,
                "mac_valid": mac_valid,
                "mac_hex": p['ao_mac'].hex(),
            })

            all_raw.append(p['raw'])

        session_info = {
            "client_addr": client_addr,
            "server_addr": server_addr,
            "client_port": client_port,
            "server_port": server_port,
            "ip_version": ip_version,
            "kdf_algorithm": found_alg,
            "covers_options": found_covers,
            "client_isn": format(client_isn, '08x'),
            "server_isn": format(server_isn, '08x'),
            "traffic_keys": {
                "client_syn": client_syn_key.hex(),
                "server_synack": server_synack_key.hex() if server_synack_key else "",
            },
            "packets": pkt_results,
        }
        audit_sessions.append(session_info)

    total_pkts = sum(len(s['packets']) for s in audit_sessions)
    total_valid = sum(
        sum(1 for p in s['packets'] if p['mac_valid'])
        for s in audit_sessions
    )
    total_invalid = total_pkts - total_valid

    audit = {
        "sessions": audit_sessions,
        "total_packets": total_pkts,
        "total_valid": total_valid,
        "total_invalid": total_invalid,
    }

    # Write audit report
    with open('/app/audit.json', 'w') as f:
        json.dump(audit, f, indent=2)
    print(f"Wrote audit.json: {total_pkts} packets, {total_valid} valid, "
          f"{total_invalid} invalid across {len(audit_sessions)} sessions")

    # Write pcap
    write_pcap(all_raw, '/app/validated.pcap')
    print(f"Wrote validated.pcap with {len(all_raw)} packets")

    # Run tshark verification
    try:
        result = subprocess.run(
            ["tshark", "-r", "/app/validated.pcap", "-V"],
            capture_output=True, text=True, timeout=30
        )
        with open('/app/tshark_verify.txt', 'w') as f:
            f.write(result.stdout)
            if result.stderr:
                f.write("\n--- STDERR ---\n")
                f.write(result.stderr)
        print(f"tshark verification saved to tshark_verify.txt")
    except FileNotFoundError:
        print("WARNING: tshark not found, skipping verification")
        with open('/app/tshark_verify.txt', 'w') as f:
            f.write("tshark not available\n")
    except Exception as e:
        print(f"WARNING: tshark error: {e}")
        with open('/app/tshark_verify.txt', 'w') as f:
            f.write(f"tshark error: {e}\n")


if __name__ == '__main__':
    main()
