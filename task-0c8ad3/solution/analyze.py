#!/usr/bin/env python3
"""Forensic analysis of multi-channel C2 network traffic with threat deconfliction.


Analyzes Zeek DNS and HTTP logs to:
1. Identify four suspicious DNS patterns by protocol markers
2. Classify each as real C2, authorized red team, or benign activity
3. Extract campaign ID and derive HMAC-SHA256 encryption key
4. Recover exfiltrated data from DNS tunneling and HTTP POST channels
5. Create YARA and Sigma detection rules
"""

import hashlib
import hmac as hmac_mod
import base64
import json
import os
import uuid
from collections import Counter, defaultdict


def parse_zeek_log(filepath):
    """Parse a Zeek tab-separated log file into a list of dicts."""
    headers = []
    records = []
    with open(filepath) as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("#fields"):
                headers = line.split("\t")[1:]
            elif line.startswith("#"):
                continue
            elif headers and line.strip():
                fields = line.split("\t")
                record = dict(zip(headers, fields))
                records.append(record)
    return records


def analyze_suspicious_dns(dns_records):
    """Identify and classify four suspicious DNS patterns.

    Uses a two-pass approach:
    Pass 1: Directly find TXT-based DNS tunneling by separator markers
            (.d. = real C2, .r. = authorized red team)
    Pass 2: Find A-query patterns with many unique subdomains
            (monitoring probes, dev testing)
    """
    # --- Pass 1: Find TXT-based tunneling by separator markers ---
    c2_domain = None
    redteam_domain = None

    for r in dns_records:
        query = r.get("query", "")
        qtype = r.get("qtype_name", "")

        if qtype == "TXT" and ".d." in query:
            if c2_domain is None:
                d_idx = query.index(".d.")
                c2_domain = query[d_idx + 3:]

        elif qtype == "TXT" and ".r." in query:
            if redteam_domain is None:
                r_idx = query.index(".r.")
                redteam_domain = query[r_idx + 3:]

    # --- Pass 2: Find non-TXT suspicious patterns by subdomain diversity ---
    # Group by 3-label base domain for non-TXT queries
    domain_groups = defaultdict(lambda: {
        "unique_subs": set(), "source_ips": set(),
        "rcodes": Counter(),
    })

    known_bases = set()
    if c2_domain:
        known_bases.add(c2_domain)
    if redteam_domain:
        known_bases.add(redteam_domain)

    for r in dns_records:
        qtype = r.get("qtype_name", "")
        if qtype == "TXT":
            continue

        query = r.get("query", "")
        parts = query.split(".")
        if len(parts) < 4:
            continue

        # Use 3-label base to capture the full registered domain
        base3 = ".".join(parts[-3:])

        # Skip domains already classified as C2 or redteam
        if base3 in known_bases:
            continue

        first_label = parts[0]
        if len(first_label) < 10:
            continue

        domain_groups[base3]["unique_subs"].add(first_label)
        domain_groups[base3]["source_ips"].add(r.get("id.orig_h", ""))
        domain_groups[base3]["rcodes"][r.get("rcode_name", "")] += 1

    # Classify high-diversity A-query patterns
    decoy_domains = []
    classifications = {}

    if c2_domain:
        classifications[c2_domain] = "active_c2"
    if redteam_domain:
        classifications[redteam_domain] = "authorized_redteam"

    for base, stats in domain_groups.items():
        if len(stats["unique_subs"]) < 10:
            continue

        source_count = len(stats["source_ips"])
        has_nxdomain = "NXDOMAIN" in stats["rcodes"]

        if source_count > 3:
            decoy_domains.append(base)
            classifications[base] = "benign_monitoring"
        elif has_nxdomain:
            decoy_domains.append(base)
            classifications[base] = "benign_testing"

    return c2_domain, redteam_domain, sorted(decoy_domains), classifications


def find_c2_dns_queries(dns_records, c2_domain):
    """Extract all DNS queries targeting the C2 domain via .d. separator."""
    c2_queries = []
    for r in dns_records:
        query = r.get("query", "")
        if query.endswith(f".d.{c2_domain}"):
            c2_queries.append(r)
    return c2_queries


def extract_campaign_id(c2_queries):
    """Find the init beacon and decode the campaign ID."""
    for r in c2_queries:
        query = r["query"]
        parts = query.split(".")
        if parts[0] == "init":
            b32_cid = parts[1]
            padding = (8 - len(b32_cid) % 8) % 8
            campaign_id = base64.b32decode(
                b32_cid.upper() + "=" * padding
            ).decode()
            return campaign_id
    raise RuntimeError("Init beacon not found")


def reconstruct_dns_data(c2_queries, key):
    """Reassemble DNS-tunneled data chunks, base32-decode, XOR-decrypt."""
    data_chunks = {}
    for r in c2_queries:
        query = r["query"]
        parts = query.split(".")
        prefix = parts[0]
        if prefix in ("init", "fini"):
            continue
        try:
            seq = int(prefix, 16)
            chunk = parts[1]
            data_chunks[seq] = chunk
        except ValueError:
            continue

    encoded = "".join(data_chunks[i] for i in sorted(data_chunks.keys()))
    padding = (8 - len(encoded) % 8) % 8
    encrypted = base64.b32decode(encoded.upper() + "=" * padding)

    decrypted = bytes(
        d ^ key[i % len(key)] for i, d in enumerate(encrypted)
    )
    return decrypted


def reconstruct_http_data(http_records, compromised_ip, c2_http_domain,
                          key, stream_offset):
    """Extract and decrypt HTTP POST exfiltration data."""
    exfil_posts = []
    for r in http_records:
        if (r.get("id.orig_h") == compromised_ip
                and r.get("host") == c2_http_domain
                and r.get("method") == "POST"
                and "d=" in r.get("uri", "")):
            exfil_posts.append(r)

    chunks = {}
    for r in exfil_posts:
        uri = r["uri"]
        if "?" in uri:
            qs = uri.split("?", 1)[1]
            params = {}
            for param in qs.split("&"):
                if "=" in param:
                    k, v = param.split("=", 1)
                    params[k] = v
            if "d" in params and "seq" in params:
                seq = int(params["seq"])
                chunks[seq] = params["d"]

    encoded = "".join(chunks[i] for i in sorted(chunks.keys()))
    encrypted = base64.b64decode(encoded)

    decrypted = bytes(
        d ^ key[(stream_offset + i) % len(key)]
        for i, d in enumerate(encrypted)
    )
    return decrypted, len(exfil_posts)


def analyze_http_beaconing(http_records, compromised_ip):
    """Find periodic HTTP beaconing from the compromised host."""
    host_timestamps = defaultdict(list)
    for r in http_records:
        if (r.get("id.orig_h") == compromised_ip
                and r.get("method") == "GET"):
            host = r.get("host", "")
            host_timestamps[host].append(float(r["ts"]))

    best_host = None
    best_interval = None
    best_count = 0

    for host, timestamps in host_timestamps.items():
        if len(timestamps) < 10:
            continue
        timestamps.sort()
        intervals = [
            timestamps[i + 1] - timestamps[i]
            for i in range(len(timestamps) - 1)
        ]
        if not intervals:
            continue
        median = sorted(intervals)[len(intervals) // 2]
        variance = sum((iv - median) ** 2 for iv in intervals) / len(intervals)
        if variance < 100 and len(timestamps) > best_count:
            best_host = host
            best_interval = round(median)
            best_count = len(timestamps)

    return best_host, best_interval


def create_yara_rule():
    """Create a YARA detection rule for the malware fragment."""
    rule = r'''rule C2_Implant_StreamCipher_Exfil {
    meta:
        description = "Detects multi-channel C2 implant with stream cipher exfiltration"
        author = "IR Team"
        date = "2024-03-01"

    strings:
        $cls_stream = "StreamCipher" ascii
        $cls_dns = "DNSExfil" ascii
        $cls_http = "HTTPExfil" ascii
        $key_derive = "derive_key" ascii
        $hmac_call = "hmac.new" ascii
        $xor_op = "stream_offset" ascii
        $chunk = "CHUNK_SIZE" ascii
        $init_beacon = "send_init" ascii
        $fini_marker = "fini" ascii
        $b32 = "b32encode" ascii

    condition:
        5 of them
}
'''
    return rule


def create_sigma_rule(c2_domain):
    """Design a Sigma detection rule for the DNS C2 tunneling channel."""
    rule_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, c2_domain))
    return f"""title: DNS Tunneling C2 via TXT Queries with Base32 Encoding and Data Separator
id: {rule_id}
status: experimental
description: >
    Detects DNS-based command and control using TXT queries with base32-encoded
    subdomain data and .d. label separator pattern. This rule specifically targets
    the protocol implementation found in the recovered malware fragment and will
    not match authorized red team exercises using .r. separators or base64url encoding.
author: IR Team
date: 2024/03/01
logsource:
    category: dns
    product: zeek
detection:
    selection_qtype:
        qtype_name: TXT
    selection_c2_domain:
        query|endswith: '.d.{c2_domain}'
    condition: selection_qtype and selection_c2_domain
falsepositives:
    - Authorized penetration testing using similar DNS tunneling techniques
      but with different separator conventions (.r. instead of .d.)
level: high
tags:
    - attack.exfiltration
    - attack.t1048.001
    - attack.command_and_control
    - attack.t1071.004
"""


def main():
    dns_records = parse_zeek_log("/app/evidence/logs/dns.log")
    http_records = parse_zeek_log("/app/evidence/logs/http.log")

    c2_dns_domain, redteam_domain, decoy_domains, classifications = \
        analyze_suspicious_dns(dns_records)

    c2_dns_queries = find_c2_dns_queries(dns_records, c2_dns_domain)

    source_ips = Counter(r["id.orig_h"] for r in c2_dns_queries)
    compromised_ip = source_ips.most_common(1)[0][0]

    campaign_id = extract_campaign_id(c2_dns_queries)

    key = hmac_mod.new(
        campaign_id.encode(), b"c2-exfil-key", hashlib.sha256
    ).digest()[:16]

    dns_data = reconstruct_dns_data(c2_dns_queries, key)

    c2_http_domain, beacon_interval = analyze_http_beaconing(
        http_records, compromised_ip
    )

    stream_offset = len(dns_data)
    http_data, http_post_count = reconstruct_http_data(
        http_records, compromised_ip, c2_http_domain, key, stream_offset
    )

    full_data = dns_data + http_data
    exfil_sha256 = hashlib.sha256(full_data).hexdigest()

    first_dns_ts = min(float(r["ts"]) for r in c2_dns_queries)
    first_http_ts = None
    for r in http_records:
        if (r.get("id.orig_h") == compromised_ip
                and r.get("host") == c2_http_domain):
            ts = float(r["ts"])
            if first_http_ts is None or ts < first_http_ts:
                first_http_ts = ts
    first_contact = min(first_dns_ts, first_http_ts) \
        if first_http_ts else first_dns_ts

    answers = {
        "c2_dns_domain": c2_dns_domain,
        "redteam_dns_domain": redteam_domain,
        "decoy_domains": decoy_domains,
        "threat_classifications": classifications,
        "c2_http_domain": c2_http_domain,
        "compromised_host_ip": compromised_ip,
        "campaign_id": campaign_id,
        "encryption_key_hex": key.hex(),
        "exfiltrated_data_sha256": exfil_sha256,
        "dns_exfil_query_count": len(c2_dns_queries),
        "http_exfil_post_count": http_post_count,
        "beacon_interval_seconds": beacon_interval,
        "first_c2_contact_epoch": int(first_contact),
    }

    with open("/app/answers.json", "w") as f:
        json.dump(answers, f, indent=2)

    os.makedirs("/app/detection", exist_ok=True)
    with open("/app/detection/implant.yar", "w") as f:
        f.write(create_yara_rule())

    with open("/app/detection/c2_dns_tunnel.yml", "w") as f:
        f.write(create_sigma_rule(c2_dns_domain))

    print("Analysis complete. Answers written to /app/answers.json")
    print("YARA rule written to /app/detection/implant.yar")
    print("Sigma rule written to /app/detection/c2_dns_tunnel.yml")
    print(json.dumps(answers, indent=2))


if __name__ == "__main__":
    main()
