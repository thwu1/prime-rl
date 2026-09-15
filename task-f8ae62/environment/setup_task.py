#!/usr/bin/env python3
"""Generate task environment: C2 profiles, binary payload samples, and HTTP traffic logs."""


import os
import json
import struct
import hashlib
import base64
import random
import string

# ============================================================
# Directory Setup
# ============================================================

for d in ['/app/profiles', '/app/samples', '/app/traffic',
          '/app/apache/htdocs', '/app/detection', '/app/analysis']:
    os.makedirs(d, exist_ok=True)

# ============================================================
# C2 Profile Definitions
# ============================================================

profiles = {
    'alpha': """[profile]
name = alpha
description = API-style beacon masquerading as REST service

[http-get]
uri = /api/v2/status
query_format = id={hex8}&token={hex16}

[http-post]
uri = /api/v2/submit
content_type = application/json

[http-stager]
uri_x86 = /api/v2/packages/x86
uri_x64 = /api/v2/packages/x64

[user-agent]
value = Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36

[headers]
X-Request-ID = {uuid}
Accept = application/json, text/plain, */*

[cookie]
format = session={base64_16_64}

[host]
teamserver = 127.0.0.1:50050
decoy = https://www.example.com
""",
    'bravo': """[profile]
name = bravo
description = CDN-style beacon masquerading as static asset requests

[http-get]
uri = /static/assets/analytics.gif
query_format = v={digit4}&cb={hex12}

[http-post]
uri = /static/assets/telemetry
content_type = application/octet-stream

[http-stager]
uri_x86 = /static/assets/logo-sm.png
uri_x64 = /static/assets/logo-lg.png

[user-agent]
value = Mozilla/5.0 (compatible; MSIE 11.0; Windows NT 10.0; Trident/7.0)

[headers]
X-CDN-Node = edge-us-east-1
X-Trace-Id = {hex16}

[cookie]
format = __cfduid={hex32}

[host]
teamserver = 127.0.0.1:50050
decoy = https://www.example.com
""",
    'charlie': """[profile]
name = charlie
description = News/RSS beacon masquerading as feed reader

[http-get]
uri = /feeds/global/rss.xml
query_format = t={digit10}&src={alpha4}

[http-post]
uri = /feeds/global/subscribe
content_type = application/x-www-form-urlencoded

[http-stager]
uri_x86 = /feeds/static/reader-x86.js
uri_x64 = /feeds/static/reader-x64.js

[user-agent]
value = FeedParser/6.0.11 (+https://feedparser.org/)

[headers]
Accept = application/rss+xml, application/xml;q=0.9

[cookie]
format = FEEDSESSID={alphanum24}

[host]
teamserver = 127.0.0.1:50050
decoy = https://www.example.com
"""
}

for name, content in profiles.items():
    with open(f'/app/profiles/{name}.profile', 'w') as f:
        f.write(content)

# ============================================================
# Binary Payload Samples
# ============================================================

def xor_encode(data, key):
    return bytes([b ^ key for b in data])

def generate_payload(implant_id, shellcode_marker, xor_key, seed):
    """Generate a binary with PE-like structure, wide-encoded implant ID,
    and XOR-encoded shellcode marker."""
    rng = random.Random(seed)
    data = bytearray(8192)

    # Fill with deterministic pseudo-random bytes
    for i in range(8192):
        data[i] = rng.randint(0, 255)

    # MZ header at offset 0
    data[0:2] = b'MZ'
    data[2:60] = b'\x90' * 58
    # e_lfanew pointing to PE signature at offset 64
    struct.pack_into('<I', data, 60, 64)
    # PE signature
    data[64:68] = b'PE\x00\x00'

    # Wide-encoded (UTF-16LE) implant identifier at offset 0x300
    wide_str = implant_id.encode('utf-16-le')
    data[0x300:0x300 + len(wide_str)] = wide_str
    # Null terminator for wide string
    data[0x300 + len(wide_str):0x300 + len(wide_str) + 2] = b'\x00\x00'

    # XOR key byte at offset 0x500
    data[0x500] = xor_key

    # XOR-encoded shellcode marker at offset 0x501
    encoded = xor_encode(shellcode_marker, xor_key)
    data[0x501:0x501 + len(encoded)] = encoded

    return bytes(data)


def generate_clean_pe(seed):
    """Generate a clean PE-like binary with no C2 indicators."""
    rng = random.Random(seed)
    data = bytearray(8192)
    for i in range(8192):
        data[i] = rng.randint(0, 255)
    data[0:2] = b'MZ'
    data[2:60] = b'\x90' * 58
    struct.pack_into('<I', data, 60, 64)
    data[64:68] = b'PE\x00\x00'
    # Decoy string (not matching any implant ID pattern)
    decoy = b'LEGITIMATE_APP_v1.0'
    data[0x300:0x300 + len(decoy)] = decoy
    return bytes(data)


def generate_clean_elf(seed):
    """Generate a clean ELF-like binary."""
    rng = random.Random(seed)
    data = bytearray(8192)
    for i in range(8192):
        data[i] = rng.randint(0, 255)
    data[0:4] = b'\x7fELF'
    data[4] = 2    # 64-bit
    data[5] = 1    # little-endian
    data[6] = 1    # ELF version
    return bytes(data)


# Shellcode preambles (common x64 patterns)
alpha_shellcode = b'\xfc\x48\x83\xe4\xf0\xe8\xcc\x00\x00\x00\x41\x51\x41\x50\x52\x51'
bravo_shellcode = b'\x48\x31\xc9\x48\x81\xe9\xdd\xff\xff\xff\x48\x8d\x05\xfe\xff\xff\xff'
charlie_shellcode = b'\xe8\x00\x00\x00\x00\x5b\x48\x83\xeb\x05\x48\x89\xdf\x48\x83\xc7\x4a'

# Generate payloads
payload_001 = generate_payload('ALPHA_IMPLANT_v2.7', alpha_shellcode, 0x3C, seed=101)
payload_002 = generate_payload('BR4VO_IMPLANT_3.1', bravo_shellcode, 0x7A, seed=202)
payload_003 = generate_payload('CH_IMP_CHARLIE_4', charlie_shellcode, 0x55, seed=303)

# Generate clean samples
clean_001 = generate_clean_pe(seed=901)
clean_002 = generate_clean_elf(seed=902)

# Write all samples
with open('/app/samples/payload_001.bin', 'wb') as f:
    f.write(payload_001)
with open('/app/samples/payload_002.bin', 'wb') as f:
    f.write(payload_002)
with open('/app/samples/payload_003.bin', 'wb') as f:
    f.write(payload_003)
with open('/app/samples/clean_001.bin', 'wb') as f:
    f.write(clean_001)
with open('/app/samples/clean_002.bin', 'wb') as f:
    f.write(clean_002)

# ============================================================
# HTTP Traffic Log
# ============================================================

rng = random.Random(42)
traffic_entries = []


def log_entry(method, uri, ua, cookie, status, src_ip, timestamp, headers=None):
    entry = {
        'timestamp': timestamp,
        'src_ip': src_ip,
        'method': method,
        'uri': uri,
        'user_agent': ua,
        'cookie': cookie,
        'status': status,
        'response_size': rng.randint(200, 50000),
    }
    if headers:
        entry['headers'] = headers
    return entry


# --- Alpha beacon traffic (10.0.0.50) ---
for i in range(12):
    ts = f'2024-11-15T{10 + i // 4:02d}:{15 * (i % 4):02d}:00Z'
    hid = hashlib.md5(f'alpha{i}'.encode()).hexdigest()[:8]
    tok = hashlib.md5(f'token{i}'.encode()).hexdigest()[:16]
    sess = base64.b64encode(rng.randbytes(24) if hasattr(rng, 'randbytes')
                            else bytes(rng.randint(0, 255) for _ in range(24))).decode()
    traffic_entries.append(log_entry(
        'GET', f'/api/v2/status?id={hid}&token={tok}',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        f'session={sess}', 200, '10.0.0.50', ts,
        headers={'X-Request-ID': f'{hid[:8]}-{tok[:4]}-{tok[4:8]}-{tok[8:12]}-{tok[12:16]}{hid}',
                 'Accept': 'application/json, text/plain, */*'}
    ))
    if i % 3 == 0:
        traffic_entries.append(log_entry(
            'POST', '/api/v2/submit',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            f'session={sess}', 200, '10.0.0.50', ts,
            headers={'X-Request-ID': f'{hid[:8]}-{tok[:4]}-{tok[4:8]}-{tok[8:12]}-{tok[12:16]}{hid}',
                     'Content-Type': 'application/json'}
        ))

# --- Bravo beacon traffic (10.0.0.75) ---
for i in range(10):
    ts = f'2024-11-15T{9 + i // 3:02d}:{20 * (i % 3):02d}:00Z'
    v = f'{rng.randint(1000, 9999)}'
    cb = hashlib.md5(f'bravo{i}'.encode()).hexdigest()[:12]
    cfd = hashlib.md5(f'cfd{i}'.encode()).hexdigest()
    traffic_entries.append(log_entry(
        'GET', f'/static/assets/analytics.gif?v={v}&cb={cb}',
        'Mozilla/5.0 (compatible; MSIE 11.0; Windows NT 10.0; Trident/7.0)',
        f'__cfduid={cfd}', 200, '10.0.0.75', ts,
        headers={'X-CDN-Node': 'edge-us-east-1', 'X-Trace-Id': cb}
    ))
    if i % 4 == 0:
        traffic_entries.append(log_entry(
            'POST', '/static/assets/telemetry',
            'Mozilla/5.0 (compatible; MSIE 11.0; Windows NT 10.0; Trident/7.0)',
            f'__cfduid={cfd}', 200, '10.0.0.75', ts,
            headers={'Content-Type': 'application/octet-stream', 'X-CDN-Node': 'edge-us-east-1', 'X-Trace-Id': cb}
        ))

# --- Charlie beacon traffic (10.0.0.120) ---
for i in range(8):
    ts = f'2024-11-15T{11 + i // 2:02d}:{30 * (i % 2):02d}:00Z'
    t = f'{1700000000 + i * 300}'
    src_vals = ['news', 'blog', 'main', 'feed']
    src = src_vals[i % 4]
    sessid = ''.join(rng.choices(string.ascii_letters + string.digits, k=24))
    traffic_entries.append(log_entry(
        'GET', f'/feeds/global/rss.xml?t={t}&src={src}',
        'FeedParser/6.0.11 (+https://feedparser.org/)',
        f'FEEDSESSID={sessid}', 200, '10.0.0.120', ts,
        headers={'Accept': 'application/rss+xml, application/xml;q=0.9'}
    ))
    if i % 3 == 0:
        traffic_entries.append(log_entry(
            'POST', '/feeds/global/subscribe',
            'FeedParser/6.0.11 (+https://feedparser.org/)',
            f'FEEDSESSID={sessid}', 200, '10.0.0.120', ts,
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        ))

# --- Legitimate traffic (192.168.x.x) ---
legit_uas = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
    'Googlebot/2.1 (+http://www.google.com/bot.html)',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'curl/8.4.0',
    'python-requests/2.31.0',
]
legit_uris = [
    '/', '/index.html', '/about', '/contact', '/robots.txt',
    '/favicon.ico', '/sitemap.xml', '/blog', '/products', '/login',
]

for i in range(20):
    ts = f'2024-11-15T{8 + i // 3:02d}:{(i * 7) % 60:02d}:00Z'
    ip = f'192.168.{rng.randint(1, 254)}.{rng.randint(1, 254)}'
    traffic_entries.append(log_entry(
        rng.choice(['GET', 'HEAD']),
        rng.choice(legit_uris),
        rng.choice(legit_uas),
        '', rng.choice([200, 301, 404]), ip, ts
    ))

# --- Analyst probing traffic (172.16.0.10) ---
probe_uris = [
    '/api/v2/status?id=test',
    '/api/v2/submit',
    '/static/assets/analytics.gif?v=1&cb=test',
    '/static/assets/telemetry',
    '/feeds/global/rss.xml',
    '/feeds/global/subscribe',
]
for i in range(6):
    ts = f'2024-11-15T{14 + i // 3:02d}:{(i * 10) % 60:02d}:00Z'
    traffic_entries.append(log_entry(
        'GET', probe_uris[i],
        'curl/8.4.0',
        '', 200, '172.16.0.10', ts
    ))

# Sort by timestamp
traffic_entries.sort(key=lambda x: x['timestamp'])

with open('/app/traffic/access.log', 'w') as f:
    json.dump(traffic_entries, f, indent=2)

# Write a default index page for Apache
with open('/app/apache/htdocs/index.html', 'w') as f:
    f.write('<html><body>Default Page</body></html>\n')

print(f"Task environment setup complete.")
print(f"  Profiles: {len(profiles)}")
print(f"  Samples: 3 payloads + 2 clean")
print(f"  Traffic entries: {len(traffic_entries)}")
