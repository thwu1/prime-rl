#!/usr/bin/env python3
"""
Generate PCAP capture files with TCP handshakes for SIP ALG scenarios.
Each file contains a TCP 3-way handshake to port 5060 with the target
MSS value in the server's SYN-ACK, plus noise traffic on other ports.

"""
import struct
import os


def pcap_global_header():
    """PCAP global header: magic, version 2.4, snaplen 65535, LINKTYPE_ETHERNET."""
    return struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)


def pcap_record(ts_sec, ts_usec, data):
    """PCAP packet record header + data."""
    return struct.pack('<IIII', ts_sec, ts_usec, len(data), len(data)) + data


def ip_bytes(addr):
    """Convert dotted-quad IP string to 4 bytes."""
    return bytes(int(x) for x in addr.split('.'))


def eth(dst, src, payload):
    """Ethernet II frame (IPv4)."""
    return dst + src + struct.pack('>H', 0x0800) + payload


def ipv4(src, dst, proto, payload, ident=0):
    """IPv4 header (20 bytes, no options) + payload."""
    total = 20 + len(payload)
    hdr = struct.pack('>BBHHHBBH', 0x45, 0, total, ident, 0x4000, 64, proto, 0)
    return hdr + ip_bytes(src) + ip_bytes(dst) + payload


def tcp_hdr(sport, dport, seq, ack, flags, opts=b''):
    """TCP header with optional options (auto-padded to 4-byte boundary)."""
    pad = (4 - len(opts) % 4) % 4
    opts += b'\x00' * pad
    doff = 5 + len(opts) // 4
    off_flags = (doff << 12) | flags
    hdr = struct.pack('>HHIIHHHH', sport, dport, seq, ack,
                      off_flags, 65535, 0, 0)
    return hdr + opts


def opt_mss(val):
    """TCP MSS option (kind=2, len=4)."""
    return struct.pack('>BBH', 2, 4, val)


def opt_sack_perm():
    """TCP SACK-Permitted option (kind=4, len=2)."""
    return struct.pack('>BB', 4, 2)


def opt_wscale(shift):
    """TCP Window Scale option (kind=3, len=3)."""
    return struct.pack('>BBB', 3, 3, shift)


NOP = b'\x01'

CLIENT_MAC = b'\x08\x00\x27\xa1\xb2\xc3'
SERVER_MAC = b'\x52\x54\x00\xd4\xe5\xf6'
GW_MAC     = b'\x00\x1a\x2b\x3c\x4d\x5e'
CLIENT_IP  = '192.168.1.100'
SERVER_IP  = '93.184.216.34'

SYN     = 0x0002
SYNACK  = 0x0012
ACK     = 0x0010

SCENARIOS = {
    'chrome_standard':   {'server_mss': 1460, 'client_mss': 1460, 'noise_mss': 1380},
    'firefox_small_mss': {'server_mss': 536,  'client_mss': 1460, 'noise_mss': 1460},
    'safari_strict_alg': {'server_mss': 1200, 'client_mss': 1460, 'noise_mss': 1380},
    'edge_jumbo_mss':    {'server_mss': 2920, 'client_mss': 1460, 'noise_mss': 1460},
}


def build_pcap(params):
    """Build a complete PCAP with noise traffic and the target handshake."""
    pkts = []
    ts = 1700000000

    # --- Noise: UDP DNS query ---
    udp = struct.pack('>HHHH', 52341, 53, 28, 0) + b'\x00' * 20
    p = eth(GW_MAC, CLIENT_MAC, ipv4(CLIENT_IP, '8.8.8.8', 17, udp, 0x1001))
    pkts.append(pcap_record(ts, 0, p))

    # --- Noise: TCP 3-way handshake to port 80 ---
    o = opt_mss(params['noise_mss']) + NOP + NOP + opt_sack_perm()
    p = eth(SERVER_MAC, CLIENT_MAC,
            ipv4(CLIENT_IP, SERVER_IP, 6,
                 tcp_hdr(44100, 80, 1000, 0, SYN, o), 0x2001))
    pkts.append(pcap_record(ts, 100000, p))

    o = opt_mss(1460) + NOP + NOP + opt_sack_perm()
    p = eth(CLIENT_MAC, SERVER_MAC,
            ipv4(SERVER_IP, CLIENT_IP, 6,
                 tcp_hdr(80, 44100, 2000, 1001, SYNACK, o), 0x2002))
    pkts.append(pcap_record(ts, 200000, p))

    p = eth(SERVER_MAC, CLIENT_MAC,
            ipv4(CLIENT_IP, SERVER_IP, 6,
                 tcp_hdr(44100, 80, 1001, 2001, ACK), 0x2003))
    pkts.append(pcap_record(ts, 300000, p))

    # --- Target: TCP 3-way handshake to port 5060 ---
    o = opt_mss(params['client_mss']) + NOP + NOP + opt_sack_perm()
    p = eth(SERVER_MAC, CLIENT_MAC,
            ipv4(CLIENT_IP, SERVER_IP, 6,
                 tcp_hdr(49152, 5060, 3000, 0, SYN, o), 0x3001))
    pkts.append(pcap_record(ts, 400000, p))

    o = (opt_mss(params['server_mss']) + NOP + NOP +
         opt_sack_perm() + NOP + opt_wscale(7))
    p = eth(CLIENT_MAC, SERVER_MAC,
            ipv4(SERVER_IP, CLIENT_IP, 6,
                 tcp_hdr(5060, 49152, 4000, 3001, SYNACK, o), 0x3002))
    pkts.append(pcap_record(ts, 500000, p))

    p = eth(SERVER_MAC, CLIENT_MAC,
            ipv4(CLIENT_IP, SERVER_IP, 6,
                 tcp_hdr(49152, 5060, 3001, 4001, ACK), 0x3003))
    pkts.append(pcap_record(ts, 600000, p))

    # --- Noise: TCP SYN to port 443 (incomplete handshake) ---
    o = opt_mss(1380) + NOP + NOP + opt_sack_perm()
    p = eth(GW_MAC, CLIENT_MAC,
            ipv4(CLIENT_IP, '10.0.0.1', 6,
                 tcp_hdr(55000, 443, 5000, 0, SYN, o), 0x4001))
    pkts.append(pcap_record(ts, 700000, p))

    return pcap_global_header() + b''.join(pkts)


def main():
    outdir = '/app/captures'
    os.makedirs(outdir, exist_ok=True)
    for sid, params in SCENARIOS.items():
        path = os.path.join(outdir, f'{sid}.pcap')
        with open(path, 'wb') as f:
            f.write(build_pcap(params))
        print(f'{path}: server_mss={params["server_mss"]}')


if __name__ == '__main__':
    main()
