#!/usr/bin/env python3
"""Generate PCAP files encoding LDP label-to-FEC bindings for each router."""

import struct
import os

CAPTURES_DIR = "/app/captures"


def ip_to_bytes(ip_str):
    return bytes(int(x) for x in ip_str.split('.'))


def write_pcap_header(f):
    f.write(struct.pack('<IHHiIII',
        0xa1b2c3d4,  # magic number (little-endian)
        2, 4,         # version major, minor
        0,            # timezone offset
        0,            # timestamp accuracy
        65535,        # snap length
        1             # link-layer type: LINKTYPE_ETHERNET
    ))


def write_packet(f, pkt_data, ts_sec):
    f.write(struct.pack('<IIII',
        ts_sec, 0,            # timestamp sec, usec
        len(pkt_data),        # captured length
        len(pkt_data)         # original length
    ))
    f.write(pkt_data)


def make_mpls_packet(mpls_label, src_ip, dst_ip):
    """Create an Ethernet + MPLS + IP packet encoding a label-FEC binding."""
    # Ethernet header (14 bytes)
    eth = b'\x00\x11\x22\x33\x44\x55'   # dst MAC
    eth += b'\x00\xaa\xbb\xcc\xdd\xee'  # src MAC
    eth += struct.pack('>H', 0x8847)     # EtherType: MPLS Unicast

    # MPLS shim header (4 bytes): label(20)|TC(3)|S(1)|TTL(8)
    mpls_shim = struct.pack('>I',
        (mpls_label << 12) | (0 << 9) | (1 << 8) | 64)

    # Minimal IP header (20 bytes)
    ip_hdr = struct.pack('>BBHHHBBH',
        0x45, 0, 40, 0, 0, 64, 17, 0)
    ip_hdr += ip_to_bytes(src_ip) + ip_to_bytes(dst_ip)

    # UDP-sized zero payload (20 bytes)
    payload = b'\x00' * 20

    return eth + mpls_shim + ip_hdr + payload


LDP_LABELS = {
    "PE1": {
        "loopback": "10.0.0.1",
        "bindings": {
            "10.0.0.1": 3, "10.0.0.2": 102, "10.0.0.3": 103,
            "10.0.0.11": 111, "10.0.0.12": 112, "10.0.0.13": 113, "10.0.0.14": 114
        }
    },
    "PE2": {
        "loopback": "10.0.0.2",
        "bindings": {
            "10.0.0.1": 201, "10.0.0.2": 3, "10.0.0.3": 203,
            "10.0.0.11": 211, "10.0.0.12": 212, "10.0.0.13": 213, "10.0.0.14": 214
        }
    },
    "PE3": {
        "loopback": "10.0.0.3",
        "bindings": {
            "10.0.0.1": 301, "10.0.0.2": 302, "10.0.0.3": 3,
            "10.0.0.11": 311, "10.0.0.12": 312, "10.0.0.13": 313, "10.0.0.14": 314
        }
    },
    "P1": {
        "loopback": "10.0.0.11",
        "bindings": {
            "10.0.0.1": 1101, "10.0.0.2": 1102, "10.0.0.3": 1103,
            "10.0.0.11": 3, "10.0.0.12": 1112, "10.0.0.13": 1113, "10.0.0.14": 1114
        }
    },
    "P2": {
        "loopback": "10.0.0.12",
        "bindings": {
            "10.0.0.1": 1201, "10.0.0.2": 1202, "10.0.0.3": 1203,
            "10.0.0.11": 1211, "10.0.0.12": 3, "10.0.0.13": 1213, "10.0.0.14": 1214
        }
    },
    "P3": {
        "loopback": "10.0.0.13",
        "bindings": {
            "10.0.0.1": 1301, "10.0.0.2": 1302, "10.0.0.3": 1303,
            "10.0.0.11": 1311, "10.0.0.12": 1312, "10.0.0.13": 3, "10.0.0.14": 1314
        }
    },
    "P4": {
        "loopback": "10.0.0.14",
        "bindings": {
            "10.0.0.1": 1401, "10.0.0.2": 1402, "10.0.0.3": 1403,
            "10.0.0.11": 1411, "10.0.0.12": 1412, "10.0.0.13": 1413, "10.0.0.14": 3
        }
    }
}


os.makedirs(CAPTURES_DIR, exist_ok=True)

for router_name, router_data in sorted(LDP_LABELS.items()):
    filepath = os.path.join(CAPTURES_DIR, f"{router_name}.pcap")
    with open(filepath, 'wb') as f:
        write_pcap_header(f)
        ts = 1000000
        for fec_ip, label in sorted(router_data["bindings"].items()):
            pkt = make_mpls_packet(label, router_data["loopback"], fec_ip)
            write_packet(f, pkt, ts)
            ts += 1
    print(f"Generated {filepath}")
