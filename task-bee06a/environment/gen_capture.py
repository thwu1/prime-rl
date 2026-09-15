#!/usr/bin/env python3
"""Generate a DNS capture file with embedded DNS tunnel traffic for forensics task."""
import struct
import hashlib
import base64
import random
import sys
import json
import os

random.seed(0xDEADBEEF)


def encode_dns_name(domain):
    """Encode a domain name in DNS wire format (label-length encoding)."""
    parts = domain.rstrip('.').split('.')
    result = b''
    for part in parts:
        encoded = part.encode('ascii')
        result += bytes([len(encoded)]) + encoded
    result += b'\x00'
    return result


def build_dns_query(domain, qtype=1, qclass=1, txid=None):
    """Build a raw DNS query packet in wire format."""
    if txid is None:
        txid = random.randint(0, 65535)
    flags = 0x0100  # Standard query, recursion desired
    header = struct.pack('!HHHHHH', txid, flags, 1, 0, 0, 0)
    qname = encode_dns_name(domain)
    question = qname + struct.pack('!HH', qtype, qclass)
    return header + question


def build_dns_response(domain, ip_parts, qtype=1, txid=None, use_compression=False):
    """Build a DNS response packet with an A record answer."""
    if txid is None:
        txid = random.randint(0, 65535)
    flags = 0x8180  # Response, recursion desired+available, no error
    header = struct.pack('!HHHHHH', txid, flags, 1, 1, 0, 0)
    qname = encode_dns_name(domain)
    question = qname + struct.pack('!HH', qtype, 1)
    if use_compression:
        # Use compression pointer to offset 12 (start of QNAME in question)
        answer = struct.pack('!H', 0xC00C)
    else:
        answer = encode_dns_name(domain)
    answer += struct.pack('!HH', qtype, 1)  # TYPE A, CLASS IN
    answer += struct.pack('!I', random.randint(60, 86400))  # TTL
    answer += struct.pack('!H', 4)  # RDLENGTH = 4 for A record
    answer += struct.pack('!BBBB', *ip_parts)
    return header + question + answer


def build_dns_response_multi(domain, ips, qtype=1, txid=None):
    """Build a DNS response with multiple A records, using compression pointers."""
    if txid is None:
        txid = random.randint(0, 65535)
    flags = 0x8180
    ancount = len(ips)
    header = struct.pack('!HHHHHH', txid, flags, 1, ancount, 0, 0)
    qname = encode_dns_name(domain)
    question = qname + struct.pack('!HH', qtype, 1)
    answers = b''
    for ip_parts in ips:
        answers += struct.pack('!H', 0xC00C)  # Compression pointer
        answers += struct.pack('!HH', 1, 1)   # TYPE A, CLASS IN
        answers += struct.pack('!I', random.randint(60, 86400))  # TTL
        answers += struct.pack('!H', 4)
        answers += struct.pack('!BBBB', *ip_parts)
    return header + question + answers


def build_dns_response_ns(domain, ns_domain, ns_ip, txid=None):
    """Build a DNS response with NS record in authority + glue in additional."""
    if txid is None:
        txid = random.randint(0, 65535)
    flags = 0x8180
    header = struct.pack('!HHHHHH', txid, flags, 1, 0, 1, 1)
    qname = encode_dns_name(domain)
    question = qname + struct.pack('!HH', 1, 1)
    # Authority section: NS record
    ns_rr = struct.pack('!H', 0xC00C)  # Compression pointer to domain
    ns_rr += struct.pack('!HH', 2, 1)  # TYPE NS, CLASS IN
    ns_rr += struct.pack('!I', 172800)  # TTL
    ns_name = encode_dns_name(ns_domain)
    ns_rr += struct.pack('!H', len(ns_name))
    ns_rr += ns_name
    # Additional section: A record for NS
    additional = encode_dns_name(ns_domain)
    additional += struct.pack('!HH', 1, 1)  # TYPE A, CLASS IN
    additional += struct.pack('!I', 172800)
    additional += struct.pack('!H', 4)
    additional += struct.pack('!BBBB', *ns_ip)
    return header + question + ns_rr + additional


def build_txt_response(domain, txt_data, txid=None):
    """Build a DNS response with a TXT record."""
    if txid is None:
        txid = random.randint(0, 65535)
    flags = 0x8180
    header = struct.pack('!HHHHHH', txid, flags, 1, 1, 0, 0)
    qname = encode_dns_name(domain)
    question = qname + struct.pack('!HH', 16, 1)  # QTYPE TXT
    answer = struct.pack('!H', 0xC00C)
    answer += struct.pack('!HH', 16, 1)  # TYPE TXT, CLASS IN
    answer += struct.pack('!I', 300)  # TTL
    txt_bytes = txt_data.encode('ascii')
    # TXT RDATA: one or more <length><string> sequences
    rdata = bytes([len(txt_bytes)]) + txt_bytes
    answer += struct.pack('!H', len(rdata))
    answer += rdata
    return header + question + answer


def build_mx_response(domain, mx_domain, preference=10, txid=None):
    """Build a DNS response with an MX record."""
    if txid is None:
        txid = random.randint(0, 65535)
    flags = 0x8180
    header = struct.pack('!HHHHHH', txid, flags, 1, 1, 0, 0)
    qname = encode_dns_name(domain)
    question = qname + struct.pack('!HH', 15, 1)  # QTYPE MX
    answer = struct.pack('!H', 0xC00C)
    answer += struct.pack('!HH', 15, 1)  # TYPE MX, CLASS IN
    answer += struct.pack('!I', 3600)
    mx_name = encode_dns_name(mx_domain)
    rdata = struct.pack('!H', preference) + mx_name
    answer += struct.pack('!H', len(rdata))
    answer += rdata
    return header + question + answer


def xor_encrypt(data, key):
    """XOR data with repeating key."""
    return bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])


def main():
    output_path = sys.argv[1]

    # The secret data to exfiltrate
    secret_data = json.dumps({
        "classification": "TS//COMINT",
        "project": "AUTUMN TEMPEST",
        "asset": "AX-7831",
        "key": "c7f3e2d1-4a8b-9c0e-5f6d-1234abcd5678",
        "handler": "MOCKINGBIRD",
        "contact": "2024-03-15T08:30Z",
        "location": "38.9072N,77.0369W",
        "notes": "Extraction within 72h. Cover compromised."
    }, separators=(',', ':'))

    # Derive XOR encryption key from tunnel domain name
    tunnel_domain = "cdn-telemetry.analytics-cdn.net"
    key = hashlib.sha256(tunnel_domain.encode()).digest()[:16]

    # Encrypt then base32 encode
    encrypted = xor_encrypt(secret_data.encode('utf-8'), key)
    encoded = base64.b32encode(encrypted).decode('ascii').rstrip('=')

    # Split into subdomain-safe chunks
    chunk_size = 20
    chunks = [encoded[i:i+chunk_size] for i in range(0, len(encoded), chunk_size)]
    num_tunnel_packets = len(chunks)

    # --- Cover traffic domains ---
    normal_domains = [
        "www.google.com", "mail.google.com", "drive.google.com",
        "www.facebook.com", "api.facebook.com", "graph.facebook.com",
        "www.amazon.com", "s3.amazonaws.com", "ec2.amazonaws.com",
        "github.com", "api.github.com", "raw.githubusercontent.com",
        "stackoverflow.com", "www.reddit.com", "old.reddit.com",
        "cdn.jsdelivr.net", "fonts.googleapis.com", "ajax.googleapis.com",
        "www.wikipedia.org", "en.wikipedia.org", "upload.wikimedia.org",
        "twitter.com", "api.twitter.com", "pbs.twimg.com",
        "www.linkedin.com", "www.youtube.com", "i.ytimg.com",
        "maps.google.com", "play.google.com", "accounts.google.com",
        "docs.google.com", "calendar.google.com", "translate.google.com",
        "news.ycombinator.com", "www.nytimes.com", "www.washingtonpost.com",
        "www.bbc.com", "cnn.com", "www.reuters.com",
        "outlook.office365.com", "login.microsoftonline.com",
        "www.dropbox.com", "dl.dropboxusercontent.com",
        "slack.com", "app.slack.com",
        "zoom.us", "us02web.zoom.us",
        "www.apple.com", "developer.apple.com",
    ]

    # Decoy domains (similar structure, different base domains)
    decoy_bases = [
        "metrics.analytics-cdn.net",
        "telemetry.analytics-cdn.com",
        "cdn-metrics.analytics-cdn.net",
        "cdn-telemetry.cdn-analytics.net",
        "telemetry.cdn-analytics.com",
    ]

    packets = []

    # --- Normal query packets ---
    for _ in range(200):
        domain = random.choice(normal_domains)
        pkt = build_dns_query(domain)
        packets.append(('normal_q', pkt))

    # --- Normal response packets (some with compression pointers) ---
    for _ in range(100):
        domain = random.choice(normal_domains)
        ip = [random.randint(1, 254) for _ in range(4)]
        use_comp = random.random() < 0.6  # 60% use compression
        pkt = build_dns_response(domain, ip, use_compression=use_comp)
        packets.append(('normal_r', pkt))

    # --- Multi-answer responses ---
    for _ in range(15):
        domain = random.choice(normal_domains)
        num_ips = random.randint(2, 4)
        ips = [[random.randint(1, 254) for _ in range(4)] for _ in range(num_ips)]
        pkt = build_dns_response_multi(domain, ips)
        packets.append(('normal_multi', pkt))

    # --- NS referral responses ---
    for _ in range(10):
        domain = random.choice(normal_domains).split('.')[-2] + '.' + random.choice(normal_domains).split('.')[-1]
        ns = f"ns1.{domain}"
        ns_ip = [random.randint(1, 254) for _ in range(4)]
        pkt = build_dns_response_ns(domain, ns, ns_ip)
        packets.append(('ns_referral', pkt))

    # --- TXT record responses ---
    for _ in range(8):
        domain = random.choice(normal_domains)
        txt = random.choice([
            "v=spf1 include:_spf.google.com ~all",
            "google-site-verification=abc123",
            "MS=ms12345678",
            "facebook-domain-verification=xyz789",
        ])
        pkt = build_txt_response(domain, txt)
        packets.append(('txt_resp', pkt))

    # --- MX record responses ---
    for _ in range(5):
        domain = random.choice(normal_domains)
        mx = f"mx1.{domain}"
        pkt = build_mx_response(domain, mx)
        packets.append(('mx_resp', pkt))

    # --- Decoy packets (look like tunnel but different domains) ---
    for _ in range(25):
        decoy_base = random.choice(decoy_bases)
        fake_data = base64.b32encode(random.randbytes(random.randint(6, 15))).decode().rstrip('=')
        seq = random.randint(0, 99)
        domain = f"{fake_data}.{seq:02x}.x.{decoy_base}"
        pkt = build_dns_query(domain)
        packets.append(('decoy', pkt))

    # --- AAAA query packets (type 28) ---
    for _ in range(15):
        domain = random.choice(normal_domains)
        pkt = build_dns_query(domain, qtype=28)
        packets.append(('aaaa_q', pkt))

    # --- Tunnel packets ---
    tunnel_packets = []
    for seq, chunk in enumerate(chunks):
        domain = f"{chunk}.{seq:02x}.x.{tunnel_domain}"
        pkt = build_dns_query(domain)
        tunnel_packets.append(('tunnel', pkt))

    packets.extend(tunnel_packets)

    # Shuffle everything
    random.shuffle(packets)

    # Write capture file with simple framing
    with open(output_path, 'wb') as f:
        # File header: magic + version + packet count
        f.write(b'DNSCAP\x01\x00')           # 8 bytes: magic + version
        f.write(struct.pack('!I', len(packets)))  # 4 bytes: packet count
        for tag, pkt in packets:
            f.write(struct.pack('!H', len(pkt)))  # 2-byte length prefix
            f.write(pkt)

    # Print metadata for verification
    plaintext_sha256 = hashlib.sha256(secret_data.encode('utf-8')).hexdigest()
    print(f"Total packets: {len(packets)}")
    print(f"Tunnel packets: {num_tunnel_packets}")
    print(f"Tunnel domain: {tunnel_domain}")
    print(f"Plaintext SHA256: {plaintext_sha256}")
    print(f"Plaintext length: {len(secret_data)}")

    # Count packet types
    from collections import Counter
    counts = Counter(tag for tag, _ in packets)
    for tag, count in sorted(counts.items()):
        print(f"  {tag}: {count}")


if __name__ == '__main__':
    main()
