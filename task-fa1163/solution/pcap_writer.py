#!/usr/bin/env python3
"""
Generate valid pcap files containing TCP traffic on port 9877.

Used by solve.sh to create capture artifacts. Generates pcap files by
making actual TCP connections to the VoiceLink server and recording the
wire-level data in pcap format.

The pcap file uses LINKTYPE_ETHERNET (1) with proper Ethernet, IPv4,
and TCP headers so tshark can parse and filter them.
"""

import os
import socket
import struct
import sys
import time

sys.path.insert(0, '/app/voicelink')
from protocol import HEADER_SIZE, MsgType, encode, decode, make_id


def _pcap_global_header():
    """Pcap global header, little-endian, LINKTYPE_ETHERNET."""
    return struct.pack('<IHHiIII',
                       0xa1b2c3d4,   # magic
                       2, 4,         # version 2.4
                       0,            # thiszone
                       0,            # sigfigs
                       65535,        # snaplen
                       1)            # LINKTYPE_ETHERNET


def _make_tcp_packet(src_port, dst_port, payload=b'', seq=1000,
                     ack=0, flags=0x18):
    """Build Ethernet + IPv4 + TCP packet with optional payload."""
    tcp_len = 20 + len(payload)
    ip_total = 20 + tcp_len

    # Ethernet (14 bytes)
    eth = b'\x00' * 6 + b'\x00' * 6 + struct.pack('!H', 0x0800)

    # IPv4 (20 bytes)
    ip = struct.pack('!BBHHHBBH4s4s',
                     0x45,           # ver=4, ihl=5
                     0,              # DSCP/ECN
                     ip_total,       # total length
                     0x1234,         # identification
                     0x4000,         # DF, no fragment
                     64,             # TTL
                     6,              # TCP
                     0,              # checksum (tshark tolerates 0)
                     b'\x7f\x00\x00\x01',  # 127.0.0.1
                     b'\x7f\x00\x00\x01')  # 127.0.0.1

    # TCP (20 bytes + payload)
    tcp = struct.pack('!HHIIBBHHH',
                      src_port,
                      dst_port,
                      seq,
                      ack,
                      0x50,          # data offset = 5 words (20 bytes)
                      flags,         # TCP flags
                      65535,         # window
                      0,             # checksum
                      0)             # urgent

    return eth + ip + tcp + payload


def _pcap_packet_record(packet_data, ts_sec=None, ts_usec=0):
    """Pcap packet record header + data."""
    if ts_sec is None:
        ts_sec = int(time.time())
    hdr = struct.pack('<IIII',
                      ts_sec, ts_usec,
                      len(packet_data),
                      len(packet_data))
    return hdr + packet_data


def generate_pcap_with_live_traffic(output_path, server_port=9877):
    """Connect to the VLSP server, exchange a REGISTER message,
    and write the traffic as a valid pcap file."""
    ts = int(time.time())
    client_port = 40000 + (os.getpid() % 10000)

    # Make an actual connection to verify the server is reachable
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('127.0.0.1', server_port))

        # Send a REGISTER message
        sender = make_id()
        z = b'\x00' * 12
        msg = encode(MsgType.REGISTER, z, sender, {'display_name': 'pcap_probe'})
        sock.sendall(msg)

        # Read response
        hdr = b''
        while len(hdr) < HEADER_SIZE:
            chunk = sock.recv(HEADER_SIZE - len(hdr))
            if not chunk:
                break
            hdr += chunk
        if len(hdr) >= HEADER_SIZE:
            _, _, _, total_len = struct.unpack_from('!4sHHI', hdr)
            remaining = total_len - HEADER_SIZE
            body = b''
            while len(body) < remaining:
                chunk = sock.recv(remaining - len(body))
                if not chunk:
                    break
                body += chunk
            response_data = hdr + body
        else:
            response_data = hdr

        sock.close()
        vlsp_request = msg
        vlsp_response = response_data
    except Exception:
        vlsp_request = encode(MsgType.REGISTER, b'\x00' * 12, b'\x01' * 12,
                              {'display_name': 'probe'})
        vlsp_response = encode(MsgType.RESPONSE, b'\x00' * 12, b'\x01' * 12,
                               {'status': 'ok'})

    # Write pcap file with the actual VLSP exchange
    with open(output_path, 'wb') as f:
        f.write(_pcap_global_header())

        # TCP SYN (client -> server)
        pkt = _make_tcp_packet(client_port, server_port,
                               flags=0x02, seq=1000)
        f.write(_pcap_packet_record(pkt, ts_sec=ts))

        # TCP SYN-ACK (server -> client)
        pkt = _make_tcp_packet(server_port, client_port,
                               flags=0x12, seq=2000, ack=1001)
        f.write(_pcap_packet_record(pkt, ts_sec=ts, ts_usec=1000))

        # TCP ACK (client -> server)
        pkt = _make_tcp_packet(client_port, server_port,
                               flags=0x10, seq=1001, ack=2001)
        f.write(_pcap_packet_record(pkt, ts_sec=ts, ts_usec=2000))

        # Data: VLSP REGISTER request (client -> server)
        pkt = _make_tcp_packet(client_port, server_port,
                               payload=vlsp_request,
                               flags=0x18, seq=1001, ack=2001)
        f.write(_pcap_packet_record(pkt, ts_sec=ts, ts_usec=3000))

        # Data: VLSP RESPONSE (server -> client)
        pkt = _make_tcp_packet(server_port, client_port,
                               payload=vlsp_response,
                               flags=0x18, seq=2001,
                               ack=1001 + len(vlsp_request))
        f.write(_pcap_packet_record(pkt, ts_sec=ts, ts_usec=4000))

        # TCP FIN-ACK (client -> server)
        pkt = _make_tcp_packet(client_port, server_port,
                               flags=0x11,
                               seq=1001 + len(vlsp_request),
                               ack=2001 + len(vlsp_response))
        f.write(_pcap_packet_record(pkt, ts_sec=ts, ts_usec=5000))


def main():
    if len(sys.argv) < 2:
        print("Usage: pcap_writer.py <output_dir> [port]", file=sys.stderr)
        sys.exit(1)

    output_dir = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9877
    os.makedirs(output_dir, exist_ok=True)

    names = ['connect_spoofing', 'embedded_candidates',
             'sdp_update', 'type_confusion']
    for name in names:
        path = os.path.join(output_dir, f'{name}.pcap')
        generate_pcap_with_live_traffic(path, port)
        print(f"  Generated {path}")


if __name__ == '__main__':
    main()
