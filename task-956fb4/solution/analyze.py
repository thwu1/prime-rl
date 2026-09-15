#!/usr/bin/env python3
"""SRv6 SRH forensic audit — solution.

Parses a LINKTYPE_RAW pcap containing IPv6+SRH packets, validates each
against RFC 8754 rules and a topology specification, computes SRH digests
and violation scores, and writes per-packet analysis and summary reports.
"""

import hashlib
import ipaddress
import json
import os
import socket
import struct
import sys


def norm(addr: str) -> str:
    return str(ipaddress.IPv6Address(addr))


def parse_pcap(path: str) -> list[dict]:
    packets: list[dict] = []
    with open(path, 'rb') as f:
        ghdr = f.read(24)
        if len(ghdr) < 24:
            sys.exit("truncated pcap global header")
        magic = struct.unpack('<I', ghdr[:4])[0]
        if magic != 0xa1b2c3d4:
            sys.exit(f"bad pcap magic: {hex(magic)}")

        while True:
            phdr = f.read(16)
            if len(phdr) < 16:
                break
            _, _, incl_len, _ = struct.unpack('<IIII', phdr)
            data = f.read(incl_len)
            if len(data) < 40:
                continue

            vtcfl = struct.unpack('!I', data[0:4])[0]
            version = (vtcfl >> 28) & 0xF
            if version != 6:
                continue
            payload_len, nxt_hdr, _ = struct.unpack('!HBB', data[4:8])
            src = norm(socket.inet_ntop(socket.AF_INET6, data[8:24]))
            dst = norm(socket.inet_ntop(socket.AF_INET6, data[24:40]))

            pkt: dict = {'src': src, 'dst': dst, 'srh': None, 'raw': data}

            if nxt_hdr == 43:
                srh_nh       = data[40]
                srh_hdr_len  = data[41]
                srh_type     = data[42]
                srh_sl       = data[43]
                srh_le       = data[44]
                srh_flags    = data[45]
                srh_tag      = struct.unpack('!H', data[46:48])[0]

                addrs: list[str] = []
                for i in range(srh_le + 1):
                    off = 48 + i * 16
                    if off + 16 <= len(data):
                        addrs.append(norm(
                            socket.inet_ntop(socket.AF_INET6,
                                             data[off:off + 16])))

                srh_size = (srh_hdr_len + 1) * 8
                srh_bytes = data[40:40 + srh_size]
                srh_digest = hashlib.sha256(srh_bytes).hexdigest()[:16]

                pkt['srh'] = {
                    'hdr_ext_len': srh_hdr_len,
                    'routing_type': srh_type,
                    'segments_left': srh_sl,
                    'last_entry': srh_le,
                    'addresses': addrs,
                    'digest': srh_digest,
                }

            packets.append(pkt)
    return packets


def analyze(pcap_path: str, topo_path: str, out_dir: str) -> None:
    with open(topo_path) as f:
        topo = json.load(f)

    valid_sids = {norm(s) for s in topo['valid_sids']}
    valid_paths = topo['valid_paths']
    violation_weights = topo['violation_weights']

    packets = parse_pcap(pcap_path)
    results: list[dict] = []
    total_violation_score = 0
    paths_seen: set[str] = set()

    for idx, pkt in enumerate(packets):
        if pkt['srh'] is None:
            results.append({
                'packet_index': idx,
                'is_valid': False,
                'errors': ['no_srh'],
                'matched_path': None,
                'srh_digest': '',
            })
            continue

        srh = pkt['srh']
        sl  = srh['segments_left']
        le  = srh['last_entry']
        hlen = srh['hdr_ext_len']
        addrs = srh['addresses']
        dst = pkt['dst']

        errors: list[str] = []

        if sl > le:
            errors.append('segments_left_exceeds_last_entry')

        if sl <= le and sl < len(addrs):
            if dst != addrs[sl]:
                errors.append('destination_mismatch')

        if hlen != 2 * (le + 1):
            errors.append('header_length_mismatch')

        if any(s not in valid_sids for s in addrs):
            errors.append('invalid_sid')

        forward = list(reversed(addrs))
        matched: str | None = None
        for p in valid_paths:
            if [norm(s) for s in p['segments']] == forward:
                matched = p['name']
                break

        if not errors and matched is None:
            errors.append('invalid_path')

        errors.sort()

        for e in errors:
            total_violation_score += violation_weights.get(e, 0)

        if matched:
            paths_seen.add(matched)

        results.append({
            'packet_index': idx,
            'is_valid': len(errors) == 0,
            'errors': errors,
            'matched_path': matched,
            'srh_digest': srh['digest'],
        })

    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, 'analysis.json'), 'w') as f:
        json.dump(results, f, indent=2)

    summary = {
        'total_packets': len(results),
        'valid_count': sum(1 for r in results if r['is_valid']),
        'invalid_count': sum(1 for r in results if not r['is_valid']),
        'violation_score': total_violation_score,
        'unique_paths_seen': sorted(paths_seen),
    }
    with open(os.path.join(out_dir, 'summary.json'), 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"Done: {summary['total_packets']} packets — "
          f"{summary['valid_count']} valid, {summary['invalid_count']} invalid")
    print(f"Violation score: {summary['violation_score']}")


if __name__ == '__main__':
    analyze('/app/captures/traffic.pcap',
            '/app/topology.json',
            '/app/output')
