#!/usr/bin/env python3
"""Generate all evidence files for DNS tunnel forensics task.
Produces: traffic.pcap, bash_history, notes.txt, exfiltool.c
"""
import struct
import hashlib
import base64
import random
import json
import sys

random.seed(0xDEADBEEF)

# ─── DNS wire format ────────────────────────────────────────────────────────

def encode_dns_name(domain):
    parts = domain.rstrip('.').split('.')
    result = b''
    for p in parts:
        enc = p.encode('ascii')
        result += bytes([len(enc)]) + enc
    result += b'\x00'
    return result


def build_dns_query(domain, qtype=1, qclass=1, txid=None):
    if txid is None:
        txid = random.randint(0, 65535)
    flags = 0x0100
    header = struct.pack('!HHHHHH', txid, flags, 1, 0, 0, 0)
    qname = encode_dns_name(domain)
    question = qname + struct.pack('!HH', qtype, qclass)
    return header + question


def build_dns_response(domain, ip_parts, qtype=1, txid=None, use_compression=False):
    if txid is None:
        txid = random.randint(0, 65535)
    flags = 0x8180
    header = struct.pack('!HHHHHH', txid, flags, 1, 1, 0, 0)
    qname = encode_dns_name(domain)
    question = qname + struct.pack('!HH', qtype, 1)
    if use_compression:
        answer = struct.pack('!H', 0xC00C)
    else:
        answer = encode_dns_name(domain)
    answer += struct.pack('!HH', qtype, 1)
    answer += struct.pack('!I', random.randint(60, 86400))
    answer += struct.pack('!H', 4)
    answer += struct.pack('!BBBB', *ip_parts)
    return header + question + answer


def build_dns_response_multi(domain, ips, qtype=1, txid=None):
    if txid is None:
        txid = random.randint(0, 65535)
    flags = 0x8180
    header = struct.pack('!HHHHHH', txid, flags, 1, len(ips), 0, 0)
    qname = encode_dns_name(domain)
    question = qname + struct.pack('!HH', qtype, 1)
    answers = b''
    for ip_parts in ips:
        answers += struct.pack('!H', 0xC00C)
        answers += struct.pack('!HH', 1, 1)
        answers += struct.pack('!I', random.randint(60, 86400))
        answers += struct.pack('!H', 4)
        answers += struct.pack('!BBBB', *ip_parts)
    return header + question + answers


def build_dns_response_ns(domain, ns_domain, ns_ip, txid=None):
    if txid is None:
        txid = random.randint(0, 65535)
    flags = 0x8180
    header = struct.pack('!HHHHHH', txid, flags, 1, 0, 1, 1)
    qname = encode_dns_name(domain)
    question = qname + struct.pack('!HH', 1, 1)
    ns_rr = struct.pack('!H', 0xC00C)
    ns_rr += struct.pack('!HH', 2, 1)
    ns_rr += struct.pack('!I', 172800)
    ns_name = encode_dns_name(ns_domain)
    ns_rr += struct.pack('!H', len(ns_name))
    ns_rr += ns_name
    additional = encode_dns_name(ns_domain)
    additional += struct.pack('!HH', 1, 1)
    additional += struct.pack('!I', 172800)
    additional += struct.pack('!H', 4)
    additional += struct.pack('!BBBB', *ns_ip)
    return header + question + ns_rr + additional


def build_txt_response(domain, txt_data, txid=None):
    if txid is None:
        txid = random.randint(0, 65535)
    flags = 0x8180
    header = struct.pack('!HHHHHH', txid, flags, 1, 1, 0, 0)
    qname = encode_dns_name(domain)
    question = qname + struct.pack('!HH', 16, 1)
    answer = struct.pack('!H', 0xC00C)
    answer += struct.pack('!HH', 16, 1)
    answer += struct.pack('!I', 300)
    txt_bytes = txt_data.encode('ascii')
    rdata = bytes([len(txt_bytes)]) + txt_bytes
    answer += struct.pack('!H', len(rdata))
    answer += rdata
    return header + question + answer


def build_mx_response(domain, mx_domain, preference=10, txid=None):
    if txid is None:
        txid = random.randint(0, 65535)
    flags = 0x8180
    header = struct.pack('!HHHHHH', txid, flags, 1, 1, 0, 0)
    qname = encode_dns_name(domain)
    question = qname + struct.pack('!HH', 15, 1)
    answer = struct.pack('!H', 0xC00C)
    answer += struct.pack('!HH', 15, 1)
    answer += struct.pack('!I', 3600)
    mx_name = encode_dns_name(mx_domain)
    rdata = struct.pack('!H', preference) + mx_name
    answer += struct.pack('!H', len(rdata))
    answer += rdata
    return header + question + answer


# ─── PCAP writing ───────────────────────────────────────────────────────────

def ip_checksum(data):
    if len(data) % 2:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i + 1]
    s = (s >> 16) + (s & 0xffff)
    s = (s >> 16) + (s & 0xffff)
    return ~s & 0xffff


def pack_ip(addr):
    return bytes(int(x) for x in addr.split('.'))


def build_pcap_packet(dns_data, ts_sec, ts_usec, src_ip, dst_ip, src_port, dst_port):
    """Build a full PCAP packet record: Ethernet + IPv4 + UDP + DNS."""
    # Ethernet header: dst(6) + src(6) + type(2) = 14 bytes
    eth = (b'\x08\x00\x27\xab\xcd\xef'   # dst MAC
           b'\x08\x00\x27\x11\x22\x33'    # src MAC
           + struct.pack('!H', 0x0800))    # EtherType: IPv4

    # UDP header
    udp_len = 8 + len(dns_data)
    udp = struct.pack('!HHHH', src_port, dst_port, udp_len, 0)

    # IPv4 header (20 bytes, no options)
    ip_total = 20 + udp_len
    ip_hdr = struct.pack('!BBHHHBBH',
                         0x45, 0, ip_total,
                         random.randint(0, 65535), 0x4000,
                         64, 17, 0)
    ip_hdr += pack_ip(src_ip) + pack_ip(dst_ip)
    csum = ip_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack('!H', csum) + ip_hdr[12:]

    pkt = eth + ip_hdr + udp + dns_data
    record_hdr = struct.pack('<IIII', ts_sec, ts_usec, len(pkt), len(pkt))
    return record_hdr + pkt


def write_pcap(output_path, pcap_packets):
    """Write a full PCAP file."""
    global_hdr = struct.pack('<IHHiIII',
                             0xa1b2c3d4,  # magic (little-endian microseconds)
                             2, 4,        # version
                             0,           # thiszone
                             0,           # sigfigs
                             65535,       # snaplen
                             1)           # LINKTYPE_ETHERNET
    with open(output_path, 'wb') as f:
        f.write(global_hdr)
        for pkt_bytes in pcap_packets:
            f.write(pkt_bytes)


# ─── Encryption helpers ─────────────────────────────────────────────────────

def xor_encrypt(data, key):
    return bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])


# ─── Main generation ────────────────────────────────────────────────────────

def main():
    # ── Secret payload ──
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

    tunnel_domain = "cdn-telemetry.analytics-cdn.net"
    key = hashlib.sha256(tunnel_domain.encode()).digest()[:16]
    encrypted = xor_encrypt(secret_data.encode('utf-8'), key)
    encoded = base64.b32encode(encrypted).decode('ascii').rstrip('=')

    chunk_size = 20
    chunks = [encoded[i:i + chunk_size] for i in range(0, len(encoded), chunk_size)]
    num_tunnel_packets = len(chunks)

    # ── Traffic domains ──
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

    decoy_bases = [
        "metrics.analytics-cdn.net",
        "telemetry.analytics-cdn.com",
        "cdn-metrics.analytics-cdn.net",
        "cdn-telemetry.cdn-analytics.net",
        "telemetry.cdn-analytics.com",
    ]

    # ── Build DNS packets (tag, dns_bytes) ──
    dns_packets = []

    # Normal queries
    for _ in range(200):
        dns_packets.append(('normal_q', build_dns_query(random.choice(normal_domains))))

    # Normal responses (some with compression)
    for _ in range(100):
        ip = [random.randint(1, 254) for _ in range(4)]
        dns_packets.append(('normal_r', build_dns_response(
            random.choice(normal_domains), ip,
            use_compression=random.random() < 0.6)))

    # Multi-answer responses
    for _ in range(15):
        ips = [[random.randint(1, 254) for _ in range(4)]
               for _ in range(random.randint(2, 4))]
        dns_packets.append(('normal_multi',
                            build_dns_response_multi(random.choice(normal_domains), ips)))

    # NS referrals
    for _ in range(10):
        d = random.choice(normal_domains)
        parts = d.split('.')
        base = '.'.join(parts[-2:])
        ns = f"ns1.{base}"
        ns_ip = [random.randint(1, 254) for _ in range(4)]
        dns_packets.append(('ns_referral', build_dns_response_ns(base, ns, ns_ip)))

    # TXT records
    txts = [
        "v=spf1 include:_spf.google.com ~all",
        "google-site-verification=abc123",
        "MS=ms12345678",
        "facebook-domain-verification=xyz789",
    ]
    for _ in range(8):
        dns_packets.append(('txt', build_txt_response(
            random.choice(normal_domains), random.choice(txts))))

    # MX records
    for _ in range(5):
        d = random.choice(normal_domains)
        dns_packets.append(('mx', build_mx_response(d, f"mx1.{d}")))

    # Decoy packets (look similar but different base domains)
    for _ in range(25):
        decoy_base = random.choice(decoy_bases)
        fake = base64.b32encode(random.randbytes(random.randint(6, 15))).decode().rstrip('=')
        seq = random.randint(0, 99)
        dns_packets.append(('decoy', build_dns_query(f"{fake}.{seq:02x}.x.{decoy_base}")))

    # AAAA queries
    for _ in range(15):
        dns_packets.append(('aaaa', build_dns_query(random.choice(normal_domains), qtype=28)))

    # Tunnel packets
    for seq, chunk in enumerate(chunks):
        domain = f"{chunk}.{seq:02x}.x.{tunnel_domain}"
        dns_packets.append(('tunnel', build_dns_query(domain)))

    random.shuffle(dns_packets)

    # ── Convert to PCAP records ──
    client_ip = "10.10.5.42"
    dns_server = "10.10.1.1"
    base_ts = 1710489000  # 2024-03-15 08:30:00 UTC

    pcap_records = []
    for i, (tag, dns_data) in enumerate(dns_packets):
        ts_sec = base_ts + i * 2 + random.randint(0, 1)
        ts_usec = random.randint(0, 999999)

        if tag in ('normal_r', 'normal_multi', 'ns_referral', 'txt', 'mx'):
            src_ip, dst_ip = dns_server, client_ip
            src_port, dst_port = 53, random.randint(1024, 65535)
        else:
            src_ip, dst_ip = client_ip, dns_server
            src_port, dst_port = random.randint(1024, 65535), 53

        pcap_records.append(
            build_pcap_packet(dns_data, ts_sec, ts_usec, src_ip, dst_ip, src_port, dst_port))

    write_pcap('/tmp/traffic.pcap', pcap_records)

    # ── Bash history ──
    bash_hist = """whoami
date
ls -la /opt/tools/
file /opt/tools/exfiltool
chmod +x /opt/tools/exfiltool
./exfiltool
./exfiltool test.example.com "hello"
cat /tmp/payload.json | wc -c
openssl enc -aes-256-cbc -pbkdf2 -in /tmp/notes.txt -out ~/.config/notes.enc -pass pass:AutumnT3mp3st
shred -u /tmp/notes.txt /tmp/payload.json
history -c
"""
    with open('/tmp/bash_history', 'w') as f:
        f.write(bash_hist.strip() + '\n')

    # ── Operational notes (will be encrypted by Dockerfile) ──
    notes = """SITREP - 2024-03-15
Operation: AUTUMN TEMPEST
Asset: AX-7831
Status: Extraction authorized

Deployment:
- Tool binary installed to workstation (/opt/tools/exfiltool)
- Channel established over DNS queries to CDN analytics infrastructure
- Payload encrypted with key derived from channel domain name
- Data encoded and split across query subdomain labels

Cleanup:
- Shred local payload and notes files after transmission
- Wipe tool binary and shell history
"""
    with open('/tmp/notes.txt', 'w') as f:
        f.write(notes.strip() + '\n')

    # ── Print verification metadata ──
    plaintext_sha256 = hashlib.sha256(secret_data.encode('utf-8')).hexdigest()
    print(f"Total packets: {len(dns_packets)}")
    print(f"Tunnel packets: {num_tunnel_packets}")
    print(f"Tunnel domain: {tunnel_domain}")
    print(f"Plaintext SHA256: {plaintext_sha256}")
    print(f"Plaintext length: {len(secret_data)}")

    from collections import Counter
    counts = Counter(tag for tag, _ in dns_packets)
    for tag, count in sorted(counts.items()):
        print(f"  {tag}: {count}")


if __name__ == '__main__':
    main()
