#!/usr/bin/env python3
"""
General-purpose DNS tunnel detector.

Analyzes a pcap file for DNS tunneling by identifying base domains with
anomalously many unique high-entropy subdomains — the statistical signature
of data exfiltration via DNS subdomain encoding.

Usage: python3 detector.py <pcap_path>
Output: JSON to stdout with detected tunnel domains.
"""


import json
import math
import struct
import sys
from collections import Counter, defaultdict


def parse_pcap_queries(pcap_path):
    """Extract DNS query names from a pcap file using raw parsing."""
    queries = []
    with open(pcap_path, "rb") as f:
        ghdr = f.read(24)
        if len(ghdr) < 24:
            return queries
        magic = struct.unpack("<I", ghdr[:4])[0]
        if magic == 0xa1b2c3d4:
            endian = "<"
        elif magic == 0xd4c3b2a1:
            endian = ">"
        else:
            return queries

        while True:
            rec_hdr = f.read(16)
            if len(rec_hdr) < 16:
                break
            _, _, incl_len, _ = struct.unpack(f"{endian}IIII", rec_hdr)
            pkt = f.read(incl_len)
            if len(pkt) < incl_len:
                break
            if len(pkt) < 54:
                continue
            if pkt[23] != 17:
                continue
            dst_port = struct.unpack("!H", pkt[36:38])[0]
            if dst_port != 53:
                continue

            dns = pkt[42:]
            if len(dns) < 12:
                continue
            flags = struct.unpack("!H", dns[2:4])[0]
            if (flags >> 15) & 1:
                continue

            pos = 12
            labels = []
            while pos < len(dns) and dns[pos] != 0:
                llen = dns[pos]
                if llen & 0xc0:
                    break
                if pos + 1 + llen > len(dns):
                    break
                pos += 1
                labels.append(
                    dns[pos:pos + llen].decode("ascii", errors="replace"))
                pos += llen

            if labels:
                queries.append(".".join(labels))

    return queries


def entropy(s):
    """Shannon entropy of a string."""
    if not s:
        return 0.0
    freq = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def detect_tunnels(queries, min_unique=8, min_entropy=2.0,
                   min_avg_length=10):
    """Detect DNS tunnel domains using statistical heuristics.

    For each candidate base domain (last N labels, N=2..5), compute:
    - Number of unique subdomain prefixes
    - Average Shannon entropy of the longest data-carrying label
    - Average prefix length

    Domains with many unique high-entropy long subdomains are flagged.
    """
    base_groups = defaultdict(set)

    for domain in queries:
        parts = domain.split(".")
        for n in range(2, min(6, len(parts))):
            base = ".".join(parts[-n:])
            prefix = ".".join(parts[:-n])
            if prefix:
                base_groups[base].add(prefix)

    candidates = []

    for base, prefixes in base_groups.items():
        n_unique = len(prefixes)
        if n_unique < min_unique:
            continue

        ents = []
        lens = []
        for p in prefixes:
            sub_labels = p.split(".")
            longest = max(sub_labels, key=len)
            ents.append(entropy(longest))
            lens.append(len(p))

        avg_ent = sum(ents) / len(ents) if ents else 0
        avg_len = sum(lens) / len(lens) if lens else 0

        if avg_ent < min_entropy:
            continue
        if avg_len < min_avg_length:
            continue

        score = n_unique * avg_ent * (avg_len / 10.0)
        candidates.append({
            "domain": base,
            "confidence": min(1.0, score / 500.0),
            "unique_subdomains": n_unique,
            "avg_entropy": round(avg_ent, 3),
            "avg_prefix_length": round(avg_len, 1),
            "score": round(score, 2),
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)

    # Filter: remove broad suffix domains when a more specific
    # domain exists (prefer cdn-telemetry.example.net over example.net)
    all_domains = {c["domain"] for c in candidates}
    filtered = []
    for c in candidates:
        is_too_broad = any(
            other.endswith("." + c["domain"])
            for other in all_domains
            if other != c["domain"]
        )
        if not is_too_broad:
            filtered.append(c)

    return filtered


def main():
    if len(sys.argv) < 2:
        print("Usage: detector.py <pcap_path>", file=sys.stderr)
        sys.exit(1)

    pcap_path = sys.argv[1]
    queries = parse_pcap_queries(pcap_path)
    tunnels = detect_tunnels(queries)

    output = {"detected_tunnels": tunnels}
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
