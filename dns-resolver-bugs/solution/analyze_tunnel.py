#!/usr/bin/env python3
"""
Analyze DNS traffic pcap to extract tunneled data and produce analysis report.

Approach:
1. Parse pcap to extract DNS query names and types
2. Statistical analysis to identify tunnel base domain
3. Reverse-engineer subdomain encoding protocol
4. Extract, decode, deduplicate, and reassemble exfiltrated data
5. Write outputs
"""


import struct
import json
import base64
import hashlib
import math
from collections import defaultdict, Counter


def parse_pcap_dns_queries(pcap_path):
    """Parse pcap file and extract DNS query names and types."""
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
            raise ValueError(f"Not a pcap: magic={hex(magic)}")

        while True:
            rec_hdr = f.read(16)
            if len(rec_hdr) < 16:
                break
            ts_sec, ts_usec, incl_len, _ = struct.unpack(
                f"{endian}IIII", rec_hdr)
            pkt = f.read(incl_len)
            if len(pkt) < incl_len:
                break

            # Ethernet(14) + IP(20) + UDP(8) = 42
            if len(pkt) < 54:
                continue
            if pkt[23] != 17:  # Not UDP
                continue
            dst_port = struct.unpack("!H", pkt[36:38])[0]
            if dst_port != 53:
                continue

            dns = pkt[42:]
            if len(dns) < 12:
                continue
            flags = struct.unpack("!H", dns[2:4])[0]
            if (flags >> 15) & 1:  # Response, skip
                continue
            qdcount = struct.unpack("!H", dns[4:6])[0]
            if qdcount < 1:
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

            if not labels:
                continue
            pos += 1
            if pos + 4 > len(dns):
                continue
            qtype = struct.unpack("!HH", dns[pos:pos + 4])[0]

            QTYPES = {1: "A", 2: "NS", 5: "CNAME", 15: "MX",
                      16: "TXT", 28: "AAAA"}

            queries.append({
                "domain": ".".join(labels),
                "qtype": QTYPES.get(qtype, str(qtype)),
                "ts_sec": ts_sec,
            })

    return queries


def compute_entropy(s):
    """Shannon entropy of a string."""
    if not s:
        return 0.0
    freq = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def identify_tunnel(queries):
    """Identify tunnel base domain via statistical analysis."""
    base_stats = defaultdict(lambda: {
        "unique_subs": set(), "total": 0, "qtypes": Counter()
    })

    for q in queries:
        parts = q["domain"].split(".")
        for n in range(2, min(6, len(parts))):
            base = ".".join(parts[-n:])
            prefix = ".".join(parts[:-n])
            base_stats[base]["unique_subs"].add(prefix)
            base_stats[base]["total"] += 1
            base_stats[base]["qtypes"][q["qtype"]] += 1

    best_score = -1
    best_base = None
    best_stats = None

    for base, stats in base_stats.items():
        n_unique = len(stats["unique_subs"])
        if n_unique < 8:
            continue

        entropies = []
        lengths = []
        for sub in stats["unique_subs"]:
            if sub:
                first_meaningful = sub.split(".")[-1] if "." in sub else sub
                entropies.append(compute_entropy(first_meaningful))
                lengths.append(len(sub))

        if not entropies:
            continue

        avg_ent = sum(entropies) / len(entropies)
        avg_len = sum(lengths) / len(lengths)

        score = n_unique * avg_ent * (avg_len / 10.0)
        if score > best_score:
            best_score = score
            best_base = base
            best_stats = stats

    return best_base, best_stats


def detect_encoding(data_labels):
    """Detect encoding from character set analysis."""
    all_chars = set()
    for label in data_labels:
        all_chars.update(label.lower())

    has_upper = any(c.isupper() for label in data_labels for c in label)
    has_special = bool(all_chars & set("-_"))
    has_g_to_z = bool(all_chars & set("ghijklmnopqrstuvwxyz"))

    if has_upper or has_special:
        return "base64url"
    elif has_g_to_z:
        return "base32"
    else:
        return "hex"


def decode_chunk(encoded, encoding):
    """Decode a single chunk."""
    if encoding == "base32":
        padded = encoded.upper() + "=" * ((-len(encoded)) % 8)
        return base64.b32decode(padded)
    elif encoding == "hex":
        return bytes.fromhex(encoded)
    elif encoding == "base64url":
        padded = encoded + "=" * ((-len(encoded)) % 4)
        return base64.urlsafe_b64decode(padded)
    raise ValueError(f"Unknown encoding: {encoding}")


def main():
    pcap_path = "/app/traffic.pcap"
    queries = parse_pcap_dns_queries(pcap_path)
    print(f"Parsed {len(queries)} DNS queries")

    tunnel_domain, stats = identify_tunnel(queries)
    print(f"Identified tunnel domain: {tunnel_domain}")

    tunnel_queries = [
        q for q in queries
        if q["domain"].endswith("." + tunnel_domain)
    ]
    print(f"Tunnel queries: {len(tunnel_queries)}")

    qtype_counter = Counter(q["qtype"] for q in tunnel_queries)
    primary_qtype = qtype_counter.most_common(1)[0][0]

    base_label_count = len(tunnel_domain.split("."))
    chunks = {}
    total_tunnel = 0
    retransmissions = 0

    for q in tunnel_queries:
        parts = q["domain"].split(".")
        prefix_parts = parts[:-base_label_count]
        if len(prefix_parts) < 2:
            continue

        seq_hex = prefix_parts[0]
        data_label = ".".join(prefix_parts[1:])

        try:
            seq = int(seq_hex, 16)
        except ValueError:
            continue

        total_tunnel += 1
        if seq in chunks:
            retransmissions += 1
        else:
            chunks[seq] = data_label

    encoding = detect_encoding(list(chunks.values()))
    print(f"Encoding: {encoding}")

    max_seq = max(chunks.keys())
    reassembled = b""
    for seq in range(max_seq + 1):
        if seq not in chunks:
            print(f"WARNING: Missing chunk {seq}")
            continue
        decoded = decode_chunk(chunks[seq], encoding)
        reassembled += decoded

    sha256 = hashlib.sha256(reassembled).hexdigest()
    print(f"Reassembled {len(reassembled)} bytes, SHA256: {sha256}")

    with open("/app/exfiltrated.bin", "wb") as f:
        f.write(reassembled)
    print("Wrote /app/exfiltrated.bin")

    analysis = {
        "tunnel_domain": tunnel_domain,
        "total_tunnel_queries": total_tunnel,
        "unique_chunks": len(chunks),
        "encoding": encoding,
        "query_type": primary_qtype,
        "retransmission_count": retransmissions,
    }
    with open("/app/tunnel_analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)
    print("Wrote /app/tunnel_analysis.json")
    print(json.dumps(analysis, indent=2))


if __name__ == "__main__":
    main()
