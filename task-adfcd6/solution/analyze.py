#!/usr/bin/env python3
"""
DNS Exfiltration Forensics Solver

Analyzes DNS resolver logs to identify covert data exfiltration channels,
determines encoding schemes, decodes exfiltrated data, and recovers XOR keys.
"""
import re
import math
import json
import hashlib
import base64
from collections import defaultdict, Counter


def parse_log(log_path):
    """Parse DNS log entries, skip comments."""
    entries = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 6:
                continue
            entries.append({
                'ts': parts[0],
                'client': parts[1],
                'qname': parts[2].lower(),
                'qtype': parts[3],
                'rcode': parts[4],
            })
    return entries


def compute_entropy(s):
    """Compute Shannon entropy of a string."""
    if not s:
        return 0
    freq = Counter(s)
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in freq.values())


def extract_parent_domain(qname):
    """
    Extract the parent/registered domain from a query name.
    Tries to find the most specific parent domain that has multiple
    queries with varying subdomains.
    """
    labels = qname.rstrip('.').split('.')
    candidates = []
    # Generate candidate parents from 2 labels up to len-1 labels
    for depth in range(2, min(len(labels), 5)):
        candidates.append('.'.join(labels[-depth:]))
    return candidates


def identify_exfil_domains(entries):
    """
    Identify exfiltration domains by scoring candidates on:
    - High ratio of unique subdomains (data encoded in labels)
    - High entropy in first subdomain labels
    - Long first labels
    - Presence of hex-format sequence numbers
    - Queries concentrated from single client IP
    """
    # Build candidate parent domains and their queries
    parent_queries = defaultdict(list)
    for entry in entries:
        qname = entry['qname']
        candidates = extract_parent_domain(qname)
        for parent in candidates:
            if qname != parent:  # Must have at least one subdomain label
                parent_queries[parent].append(entry)

    scores = {}
    info = {}

    for parent, queries in parent_queries.items():
        if len(queries) < 10:
            continue

        # Extract subdomain parts
        subdomains = []
        for q in queries:
            qname = q['qname']
            if qname.endswith('.' + parent):
                sub = qname[:-(len(parent) + 1)]
                if sub:
                    subdomains.append(sub)

        if len(subdomains) < 10:
            continue

        # Get first labels
        first_labels = [s.split('.')[0] for s in subdomains]
        unique_first = len(set(first_labels))

        # Metric 1: unique ratio
        unique_ratio = unique_first / len(first_labels)

        # Metric 2: average entropy of first labels
        avg_entropy = sum(compute_entropy(l) for l in first_labels) / len(first_labels)

        # Metric 3: average length of first labels
        avg_len = sum(len(l) for l in first_labels) / len(first_labels)

        # Metric 4: sequence number pattern (4-char hex as second label)
        seq_labels = set()
        for s in subdomains:
            parts = s.split('.')
            if len(parts) >= 2:
                candidate_seq = parts[-1]  # Last subdomain label before parent
                if re.match(r'^[0-9a-f]{4}$', candidate_seq):
                    seq_labels.add(candidate_seq)
        has_seq = len(seq_labels) >= 5

        # Metric 5: client concentration
        clients = Counter(q['client'] for q in queries)
        max_client_pct = max(clients.values()) / len(queries)

        # Score
        score = 0
        if unique_ratio > 0.85:
            score += 2
        if avg_entropy > 3.0:
            score += 2
        if avg_len > 15:
            score += 2
        if has_seq:
            score += 4
        if max_client_pct > 0.9:
            score += 2

        if score >= 8:
            scores[parent] = score
            info[parent] = {
                'queries': queries,
                'subdomains': subdomains,
                'unique_ratio': unique_ratio,
                'avg_entropy': avg_entropy,
                'avg_len': avg_len,
                'has_seq': has_seq,
                'max_client_pct': max_client_pct,
                'num_queries': len(queries),
                'score': score,
            }

    # Deduplicate: if domain A is a suffix of domain B and both found,
    # keep the longer (more specific) one
    to_remove = set()
    parents = list(scores.keys())
    for i, p1 in enumerate(parents):
        for j, p2 in enumerate(parents):
            if i != j and p1.endswith('.' + p2):
                # p1 is more specific than p2, remove p2
                to_remove.add(p2)
            elif i != j and p2.endswith('.' + p1):
                to_remove.add(p1)

    for r in to_remove:
        if r in scores:
            del scores[r]
            del info[r]

    top = sorted(scores.keys(), key=lambda d: scores[d], reverse=True)[:3]
    return top, {d: info[d] for d in top}


def extract_chunks(subdomains, parent):
    """Extract (sequence_number, data_chunk) pairs."""
    chunks = []
    for sub in subdomains:
        parts = sub.split('.')
        if len(parts) >= 2:
            seq_label = parts[-1]
            if re.match(r'^[0-9a-f]{4}$', seq_label):
                seq = int(seq_label, 16)
                data = parts[0]  # First label is the data
                chunks.append((seq, data))
    chunks.sort(key=lambda x: x[0])
    return chunks


def try_decode(chunks):
    """
    Try multiple decodings and return the first that produces readable text.
    Returns (decoded_bytes, encoding_name, xor_key_hex_or_none)
    """
    all_data = ''.join(c for _, c in chunks)

    if not all_data:
        return None, 'unknown', None

    hex_chars = set('0123456789abcdef')
    base32_chars = set('abcdefghijklmnopqrstuvwxyz234567')
    data_chars = set(all_data)

    # Try base32
    if data_chars <= base32_chars and not data_chars <= hex_chars:
        try:
            padded = all_data.upper()
            padding_needed = (8 - len(padded) % 8) % 8
            padded += '=' * padding_needed
            decoded = base64.b32decode(padded)
            if is_printable_text(decoded):
                return decoded, 'base32', None
        except Exception:
            pass

    # Try hex (direct plaintext)
    if data_chars <= hex_chars and len(all_data) % 2 == 0:
        try:
            decoded = bytes.fromhex(all_data)
            if is_printable_text(decoded):
                return decoded, 'hex', None
        except Exception:
            pass

        # Hex decodes but not printable => likely XOR encrypted
        try:
            decoded = bytes.fromhex(all_data)
            xor_key = recover_xor_key(decoded)
            if xor_key:
                decrypted = xor_decrypt(decoded, xor_key)
                if is_printable_text(decrypted):
                    return decrypted, 'xor_hex', xor_key.hex()
        except Exception:
            pass

    return None, 'unknown', None


def is_printable_text(data):
    """Check if bytes are mostly printable UTF-8 text."""
    try:
        text = data.decode('utf-8')
        printable = sum(1 for c in text if c.isprintable() or c in '\n\r\t')
        return (printable / len(text)) > 0.85 if text else False
    except UnicodeDecodeError:
        return False


def recover_xor_key(ciphertext, max_key_len=6):
    """Recover XOR key using frequency analysis and known plaintext."""
    for key_len in range(1, max_key_len + 1):
        key = bytearray(key_len)

        for pos in range(key_len):
            byte_stream = ciphertext[pos::key_len]
            if not byte_stream:
                continue

            best_byte = 0
            best_score = -1

            for candidate in range(256):
                score = 0
                for cb in byte_stream:
                    pb = cb ^ candidate
                    if 32 <= pb <= 126 or pb in (10, 13, 9):
                        score += 1
                        # Bonus for common text chars
                        if pb in (32, 34, 44, 58, 10):  # space, quote, comma, colon, newline
                            score += 0.3
                if score > best_score:
                    best_score = score
                    best_byte = candidate

            key[pos] = best_byte

        # Validate
        decrypted = xor_decrypt(ciphertext, bytes(key))
        try:
            text = decrypted.decode('utf-8')
            printable = sum(1 for c in text if c.isprintable() or c in '\n\r\t')
            ratio = printable / len(text) if text else 0
            if ratio > 0.9:
                # Extra validation: try parsing as JSON
                try:
                    json.loads(text)
                    return bytes(key)
                except json.JSONDecodeError:
                    pass
                if text.startswith('-----BEGIN') or text.startswith('root:'):
                    return bytes(key)
                if ratio > 0.95:
                    return bytes(key)
        except UnicodeDecodeError:
            continue

    return None


def xor_decrypt(data, key):
    """XOR decrypt with rotating key."""
    result = bytearray(len(data))
    for i, b in enumerate(data):
        result[i] = b ^ key[i % len(key)]
    return bytes(result)


def main():
    log_path = "/app/dns_queries.log"
    entries = parse_log(log_path)

    exfil_domains, domain_info = identify_exfil_domains(entries)

    results = {
        "exfil_domains": sorted(exfil_domains),
        "decoded_data_sha256": {},
        "xor_key_hex": "",
    }

    for domain in exfil_domains:
        info = domain_info[domain]
        chunks = extract_chunks(info['subdomains'], domain)

        decoded, encoding, xor_key_hex = try_decode(chunks)

        if decoded:
            sha = hashlib.sha256(decoded).hexdigest()
            results["decoded_data_sha256"][domain] = sha
            if xor_key_hex:
                results["xor_key_hex"] = xor_key_hex

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
