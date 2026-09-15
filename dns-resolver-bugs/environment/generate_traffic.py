#!/usr/bin/env python3
"""Generate DNS traffic pcap with embedded tunnel exfiltration.
Run during Docker build, then deleted from the image."""


import struct
import hashlib
import random
import base64
import os


def ip_checksum(data):
    if len(data) % 2:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i + 1]
    while s >> 16:
        s = (s & 0xffff) + (s >> 16)
    return ~s & 0xffff


def encode_dns_name(name):
    encoded = b""
    for label in name.encode("ascii").split(b"."):
        encoded += bytes([len(label)]) + label
    encoded += b"\x00"
    return encoded


def make_dns_query(qname_str, qtype, txid):
    dns = struct.pack("!HHHHHH", txid, 0x0100, 1, 0, 0, 0)
    dns += encode_dns_name(qname_str)
    dns += struct.pack("!HH", qtype, 1)
    return dns


def ip_bytes(ip_str):
    return bytes(int(x) for x in ip_str.split("."))


def make_pcap_packet(src_ip, dst_ip, src_port, dst_port, payload,
                     ts_sec, ts_usec, rng):
    eth = b'\x08\x00\x27\xab\xcd\xef\x08\x00\x27\x12\x34\x56'
    eth += struct.pack("!H", 0x0800)
    udp_len = 8 + len(payload)
    udp = struct.pack("!HHHH", src_port, dst_port, udp_len, 0)
    ip_total = 20 + udp_len
    ip_hdr = struct.pack("!BBHHHBBH",
                         0x45, 0x00, ip_total,
                         rng.randint(0, 65535), 0x4000,
                         64, 17, 0)
    ip_hdr += ip_bytes(src_ip) + ip_bytes(dst_ip)
    chk = ip_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack("!H", chk) + ip_hdr[12:]
    pkt = eth + ip_hdr + udp + payload
    rec = struct.pack("<IIII", ts_sec, ts_usec, len(pkt), len(pkt))
    return rec + pkt


QUERY_TYPES = {"A": 1, "AAAA": 28, "CNAME": 5, "MX": 15, "TXT": 16, "NS": 2}

LEGIT_DOMAINS = [
    "www.google.com", "mail.google.com", "maps.google.com",
    "drive.google.com", "calendar.google.com",
    "www.github.com", "api.github.com", "raw.githubusercontent.com",
    "www.stackoverflow.com", "cdn.sstatic.net",
    "www.amazon.com", "aws.amazon.com", "s3.amazonaws.com",
    "login.microsoftonline.com", "outlook.office365.com",
    "graph.microsoft.com", "fonts.googleapis.com",
    "ajax.googleapis.com", "cdnjs.cloudflare.com",
    "cdn.jsdelivr.net", "registry.npmjs.org", "pypi.org",
    "archive.ubuntu.com", "security.ubuntu.com",
    "time.google.com", "ntp.ubuntu.com",
    "ocsp.digicert.com", "crl.pki.goog",
    "collector.githubapp.com", "www.wikipedia.org",
    "en.wikipedia.org", "slack-imgs.com",
    "edgeapi.slack.com", "zoom.us",
    "updates.jenkins.io", "repo.maven.apache.org",
]


def generate_pcap(output_path, secret_seed, tunnel_domain, encoding,
                  qtype_name, num_legit, secret_size, rng_seed,
                  chunk_size=31):
    rng = random.Random(rng_seed)
    qtype_val = QUERY_TYPES[qtype_name]

    sec_rng = random.Random(secret_seed)
    secret_data = bytes(sec_rng.randint(0, 255) for _ in range(secret_size))

    chunks = []
    for i in range(0, len(secret_data), chunk_size):
        chunks.append(secret_data[i:i + chunk_size])

    base_time = 1710500000
    client_ip = "10.0.1.42"
    dns_server = "10.0.1.1"

    all_queries = []

    for _ in range(num_legit):
        domain = rng.choice(LEGIT_DOMAINS)
        qt = rng.choices(["A", "AAAA", "MX", "TXT", "NS"],
                         weights=[60, 20, 5, 10, 5])[0]
        ts = base_time + rng.randint(0, 3600)
        us = rng.randint(0, 999999)
        all_queries.append(("legit", domain, qt, ts, us))

    def encode_chunk(chunk, enc):
        if enc == "base32":
            return base64.b32encode(chunk).decode().rstrip("=").lower()
        elif enc == "hex":
            return chunk.hex()
        elif enc == "base64url":
            return base64.urlsafe_b64encode(chunk).decode().rstrip("=")
        raise ValueError(enc)

    for seq, chunk in enumerate(chunks):
        encoded = encode_chunk(chunk, encoding)
        seq_hex = f"{seq:04x}"
        fqdn = f"{seq_hex}.{encoded}.{tunnel_domain}"
        ts = base_time + 200 + seq * 5 + rng.randint(0, 2)
        us = rng.randint(0, 999999)
        all_queries.append(("tunnel", fqdn, qtype_name, ts, us))

    n_retrans = min(12, len(chunks))
    retrans_indices = rng.sample(range(len(chunks)), n_retrans)
    for idx in retrans_indices:
        chunk = chunks[idx]
        encoded = encode_chunk(chunk, encoding)
        seq_hex = f"{idx:04x}"
        fqdn = f"{seq_hex}.{encoded}.{tunnel_domain}"
        ts = base_time + 200 + idx * 5 + rng.randint(3, 8)
        us = rng.randint(0, 999999)
        all_queries.append(("tunnel", fqdn, qtype_name, ts, us))

    all_queries.sort(key=lambda x: (x[3], x[4]))

    pcap_hdr = struct.pack("<IHHiIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)

    with open(output_path, "wb") as f:
        f.write(pcap_hdr)
        for _, domain, qtn, ts, us in all_queries:
            txid = rng.randint(0, 65535)
            qtv = QUERY_TYPES.get(qtn, 1)
            try:
                dns = make_dns_query(domain, qtv, txid)
            except (ValueError, UnicodeEncodeError):
                continue
            sp = rng.randint(32768, 65535)
            pkt = make_pcap_packet(client_ip, dns_server, sp, 53,
                                   dns, ts, us, rng)
            f.write(pkt)


def main():
    os.makedirs("/app", exist_ok=True)
    generate_pcap(
        output_path="/app/traffic.pcap",
        secret_seed=98765,
        tunnel_domain="cdn-telemetry.example.net",
        encoding="base32",
        qtype_name="TXT",
        num_legit=500,
        secret_size=1847,
        rng_seed=20240315,
        chunk_size=31,
    )
    print("Generated /app/traffic.pcap")


if __name__ == "__main__":
    main()
