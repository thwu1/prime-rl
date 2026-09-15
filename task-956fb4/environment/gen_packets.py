#!/usr/bin/env python3
"""Generate SRv6 SRH test traffic with per-build randomization (DNA)."""
import json
import os
import struct
import socket
import hashlib
import ipaddress


def ipv6_to_bytes(addr):
    return socket.inet_pton(socket.AF_INET6, addr)


def norm(addr):
    return str(ipaddress.IPv6Address(addr))


def build_packet(src, dst, segleft, lastentry, hdr_ext_len, addresses, tag=0,
                 payload=b"SRV6TESTDATA0123"):
    """Build an IPv6 packet with SRH routing extension header."""
    srh = struct.pack('!BBBBBBH', 59, hdr_ext_len, 4, segleft, lastentry, 0, tag)
    for addr in addresses:
        srh += ipv6_to_bytes(addr)
    target_len = (hdr_ext_len + 1) * 8
    if len(srh) < target_len:
        srh += b'\x00' * (target_len - len(srh))
    elif len(srh) > target_len:
        srh = srh[:target_len]
    payload_length = len(srh) + len(payload)
    ipv6 = struct.pack('!IHBB', 0x60000000, payload_length, 43, 64)
    ipv6 += ipv6_to_bytes(src)
    ipv6 += ipv6_to_bytes(dst)
    return ipv6 + srh + payload


def write_pcap(filename, packets):
    with open(filename, 'wb') as f:
        f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 101))
        for i, pkt in enumerate(packets):
            f.write(struct.pack('<IIII', 1700000000 + i, 0, len(pkt), len(pkt)))
            f.write(pkt)


def compute_srh_digest(raw_pkt):
    srh_hdr_len = raw_pkt[41]
    srh_size = (srh_hdr_len + 1) * 8
    srh_bytes = raw_pkt[40:40 + srh_size]
    return hashlib.sha256(srh_bytes).hexdigest()[:16]


def main():
    os.makedirs('/app/captures', exist_ok=True)
    os.makedirs('/app/output', exist_ok=True)

    # Per-build random seed -- makes SRH digests unique per build instance
    seed = os.urandom(16)

    # Derive per-packet SRH tag values from the seed (tag is 16-bit)
    tags = []
    for i in range(12):
        h = hashlib.sha256(seed + struct.pack('!H', i)).digest()
        tags.append(int.from_bytes(h[:2], 'big'))

    S = {
        "R1": "fd9a:bc12:7e03::1",   "R1x": "fd9a:bc12:7e03::a1",
        "R2": "fd47:e801:3af2::1",   "R2x": "fd47:e801:3af2::a1",
        "R3": "fd82:14cd:90b7::1",   "R3x": "fd82:14cd:90b7::a1",
        "R4": "fdc3:6f25:e184::1",   "R4x": "fdc3:6f25:e184::a1",
        "R5": "fd05:ab93:d4c6::1",   "R5x": "fd05:ab93:d4c6::a1",
        "R6": "fd71:8e4a:2bf9::1",   "R6x": "fd71:8e4a:2bf9::a1",
    }

    topology = {
        "nodes": {
            f"R{i}": {
                "locator": f"{S[f'R{i}'].rsplit('::', 1)[0]}::/48",
                "sids": {"End": S[f"R{i}"], "End.DX6": S[f"R{i}x"]},
            } for i in range(1, 7)
        },
        "valid_sids": [S[k] for k in sorted(S.keys())],
        "valid_paths": [
            {"name": "transit-east",  "segments": [S["R1"], S["R3"], S["R5x"]]},
            {"name": "peering-west",  "segments": [S["R2"], S["R4"], S["R6x"]]},
            {"name": "backbone-core", "segments": [S["R1"], S["R2"], S["R4"], S["R5x"]]},
            {"name": "direct-south",  "segments": [S["R3"], S["R6x"]]},
            {"name": "metro-ring",    "segments": [S["R4"], S["R5"], S["R6x"]]},
        ],
        "error_types": {
            "segments_left_exceeds_last_entry":
                "Segments Left > Last Entry (RFC 8754 \u00a74.1.1)",
            "destination_mismatch":
                "IPv6 DA != Segment List[Segments Left] (RFC 8754 \u00a74.1.1)",
            "invalid_sid":
                "A SID in the Segment List is absent from valid_sids",
            "header_length_mismatch":
                "Hdr Ext Len != 2*(Last Entry + 1) for TLV-less SRH",
            "invalid_path":
                "All SIDs individually valid but segment sequence "
                "matches no entry in valid_paths",
        },
        "violation_weights": {
            "segments_left_exceeds_last_entry": 5,
            "destination_mismatch": 3,
            "header_length_mismatch": 4,
            "invalid_sid": 5,
            "invalid_path": 2,
        },
    }

    with open('/app/topology.json', 'w') as f:
        json.dump(topology, f, indent=2)

    R1, R2, R3, R4, R5, R6 = (S[f"R{i}"] for i in range(1, 7))
    R5x, R6x = S["R5x"], S["R6x"]

    pkts = [
        # Valid packets (0-5)
        build_packet("2001:db8:1::a",  R1, 2, 2, 6, [R5x, R3, R1], tag=tags[0]),
        build_packet("2001:db8:2::b",  R2, 2, 2, 6, [R6x, R4, R2], tag=tags[1]),
        build_packet("2001:db8:3::c",  R1, 3, 3, 8, [R5x, R4, R2, R1], tag=tags[2]),
        build_packet("2001:db8:4::d",  R3, 1, 1, 4, [R6x, R3], tag=tags[3]),
        build_packet("2001:db8:5::e",  R4, 2, 2, 6, [R6x, R5, R4], tag=tags[4]),
        build_packet("2001:db8:1::a",  R3, 1, 2, 6, [R5x, R3, R1], tag=tags[5]),
        # Error packets (6-11)
        build_packet("2001:db8:6::f",  R1, 4, 3, 8, [R5x, R4, R2, R1], tag=tags[6]),
        build_packet("2001:db8:7::10", R3, 2, 2, 6, [R5x, R3, R1], tag=tags[7]),
        build_packet("2001:db8:8::11", R2, 2, 2, 6, [R5x, "fd99:aaaa:bbbb::1", R2], tag=tags[8]),
        build_packet("2001:db8:9::12", R1, 2, 2, 8, [R5x, R3, R1], tag=tags[9]),
        build_packet("2001:db8:a::13", R1, 2, 2, 6, [R6x, R4, R1], tag=tags[10]),
        build_packet("2001:db8:b::14", S["R6x"], 1, 1, 6, [R6x, R3], tag=tags[11]),
    ]

    write_pcap('/app/captures/traffic.pcap', pkts)

    # ---- Compute DNA: expected analysis results ----
    valid_sids_set = {norm(s) for s in topology['valid_sids']}
    valid_paths_list = topology['valid_paths']
    violation_weights = topology['violation_weights']

    expected_analysis = []
    total_score = 0
    paths_seen = set()

    for idx, pkt_bytes in enumerate(pkts):
        digest = compute_srh_digest(pkt_bytes)

        sl = pkt_bytes[43]
        le = pkt_bytes[44]
        srh_hdr_len = pkt_bytes[41]

        addrs = []
        for i in range(le + 1):
            off = 48 + i * 16
            if off + 16 <= len(pkt_bytes):
                addrs.append(norm(
                    socket.inet_ntop(socket.AF_INET6, pkt_bytes[off:off + 16])))

        dst = norm(socket.inet_ntop(socket.AF_INET6, pkt_bytes[24:40]))

        errors = []

        if sl > le:
            errors.append('segments_left_exceeds_last_entry')

        if sl <= le and sl < len(addrs):
            if dst != addrs[sl]:
                errors.append('destination_mismatch')

        if srh_hdr_len != 2 * (le + 1):
            errors.append('header_length_mismatch')

        if any(s not in valid_sids_set for s in addrs):
            errors.append('invalid_sid')

        forward = list(reversed(addrs))
        matched = None
        for p in valid_paths_list:
            if [norm(s) for s in p['segments']] == forward:
                matched = p['name']
                break

        if not errors and matched is None:
            errors.append('invalid_path')

        errors.sort()

        for e in errors:
            total_score += violation_weights.get(e, 0)

        if matched:
            paths_seen.add(matched)

        expected_analysis.append({
            'packet_index': idx,
            'is_valid': len(errors) == 0,
            'errors': errors,
            'matched_path': matched,
            'srh_digest': digest,
        })

    expected_summary = {
        'total_packets': len(pkts),
        'valid_count': sum(1 for a in expected_analysis if a['is_valid']),
        'invalid_count': sum(1 for a in expected_analysis if not a['is_valid']),
        'violation_score': total_score,
        'unique_paths_seen': sorted(paths_seen),
    }

    dna = {
        'seed_hex': seed.hex(),
        'digests': [a['srh_digest'] for a in expected_analysis],
        'expected_analysis': expected_analysis,
        'expected_summary': expected_summary,
    }

    with open('/app/.task_dna.json', 'w') as f:
        json.dump(dna, f, indent=2)


if __name__ == '__main__':
    main()
