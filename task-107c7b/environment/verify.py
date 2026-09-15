#!/usr/bin/env python3
"""
TCP-AO packet verification driver.
Reads /app/packets.json, derives traffic keys, constructs MAC inputs,
computes MACs, and writes verification results to /app/results.json.
"""

import json
import struct
import socket
import sys

sys.path.insert(0, '/app')
from tcp_ao import derive_traffic_key, compute_mac


def find_tcp_ao_option(tcp_options):
    """Locate TCP-AO option (kind=29) in TCP options bytes.
    Returns (offset, length, keyid, rnextkeyid, mac_bytes) or None."""
    i = 0
    while i < len(tcp_options):
        kind = tcp_options[i]
        if kind == 0:
            break
        if kind == 1:
            i += 1
            continue
        if i + 1 >= len(tcp_options):
            break
        length = tcp_options[i + 1]
        if length < 2:
            break
        if kind == 29:
            return (i, length, tcp_options[i + 2], tcp_options[i + 3],
                    bytes(tcp_options[i + 4:i + length]))
        i += length
    return None


def build_ipv4_pseudoheader(src_ip, dst_ip, tcp_length):
    """Build IPv4 TCP pseudoheader."""
    return (socket.inet_pton(socket.AF_INET, src_ip) +
            socket.inet_pton(socket.AF_INET, dst_ip) +
            b'\x00\x06' + struct.pack('!H', tcp_length))


def build_ipv6_pseudoheader(src_ip, dst_ip, tcp_length):
    """Build IPv6 TCP pseudoheader."""
    return (socket.inet_pton(socket.AF_INET6, src_ip) +
            socket.inet_pton(socket.AF_INET6, dst_ip) +
            struct.pack('!I', tcp_length) + b'\x00\x00\x00\x06')


def verify_packet(packet_hex, conn):
    """Parse a raw IP/TCP packet and verify its TCP-AO MAC."""
    raw = bytes.fromhex(packet_hex)
    ip_ver = (raw[0] >> 4) & 0xF

    if ip_ver == 4:
        ihl = (raw[0] & 0xF) * 4
        total = struct.unpack('!H', raw[2:4])[0]
        ip_src = socket.inet_ntop(socket.AF_INET, raw[12:16])
        ip_dst = socket.inet_ntop(socket.AF_INET, raw[16:20])
        tcp_off = ihl
        tcp_len = total - ihl
    else:
        payload_len = struct.unpack('!H', raw[4:6])[0]
        ip_src = socket.inet_ntop(socket.AF_INET6, raw[8:24])
        ip_dst = socket.inet_ntop(socket.AF_INET6, raw[24:40])
        tcp_off = 40
        tcp_len = payload_len

    tcp = bytearray(raw[tcp_off:tcp_off + tcp_len])
    data_offset = ((tcp[12] >> 4) & 0xF) * 4
    src_port = struct.unpack('!H', tcp[0:2])[0]

    # Locate TCP-AO option in TCP options
    ao = find_tcp_ao_option(tcp[20:data_offset])
    if ao is None:
        raise ValueError("TCP-AO option not found in packet")
    ao_off_in_opts, ao_len, _, _, pkt_mac = ao

    # Extract connection parameters
    cli_ip = conn['client_ip']
    srv_ip = conn['server_ip']
    cli_port = conn['client_port']
    srv_port = conn['server_port']
    cli_isn = (int(conn['client_isn'], 16)
               if isinstance(conn['client_isn'], str)
               else conn['client_isn'])
    srv_isn = (int(conn['server_isn'], 16)
               if isinstance(conn['server_isn'], str)
               else conn['server_isn'])
    master_key = (conn['master_key'].encode('ascii')
                  if isinstance(conn['master_key'], str)
                  else conn['master_key'])

    # Determine traffic key derivation parameters based on packet direction
    if ip_src == cli_ip and src_port == cli_port:
        # Client -> Server
        tk_params = (cli_ip, srv_ip, cli_port, srv_port, cli_isn, srv_isn)
    else:
        # Server -> Client
        tk_params = (srv_ip, cli_ip, srv_port, cli_port, srv_isn, cli_isn)

    tkey = derive_traffic_key(conn['kdf_alg'], master_key, *tk_params)

    # Build IP pseudoheader (uses original TCP segment length)
    if ip_ver == 4:
        ph = build_ipv4_pseudoheader(ip_src, ip_dst, tcp_len)
    else:
        ph = build_ipv6_pseudoheader(ip_src, ip_dst, tcp_len)

    # Construct MAC input: SNE(4 bytes) + pseudoheader + modified TCP segment
    # Zero TCP checksum and TCP-AO MAC field before computing
    modified_tcp = bytearray(tcp)
    modified_tcp[16] = modified_tcp[17] = 0  # zero checksum
    mac_start = 20 + ao_off_in_opts + 4
    mac_byte_len = ao_len - 4
    for j in range(mac_byte_len):
        modified_tcp[mac_start + j] = 0  # zero MAC field
    mac_input = struct.pack('!I', 0) + ph + bytes(modified_tcp)

    computed = compute_mac(conn['mac_alg'], tkey, mac_input)

    return {
        'traffic_key': tkey.hex(),
        'computed_mac': computed.hex(),
        'packet_mac': pkt_mac.hex(),
        'verified': computed == pkt_mac,
    }


def main():
    with open('/app/packets.json') as f:
        data = json.load(f)

    results = []
    for conn in data['connections']:
        conn_info = {**conn, 'master_key': data['master_key']}
        for seg_name, pkt_hex in conn['segments'].items():
            r = verify_packet(pkt_hex, conn_info)
            r['connection_id'] = conn['id']
            r['segment'] = seg_name
            results.append(r)

    with open('/app/results.json', 'w') as f:
        json.dump({'results': results}, f, indent=2)

    passed = sum(1 for r in results if r['verified'])
    total = len(results)
    print(f"Verified {passed}/{total} packets")
    if passed < total:
        for r in results:
            if not r['verified']:
                print(f"  FAIL: {r['connection_id']}/{r['segment']}")
        sys.exit(1)


if __name__ == '__main__':
    main()
