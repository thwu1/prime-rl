#!/usr/bin/env python3
"""
Solution for binary implant family analysis and detection design challenge.


Strategy:
1. Use tshark to extract BOTH covert DNS channels from the PCAP
2. Analyze sample_alpha with radare2 to trace which cipher feeds which channel
3. Evaluate: cdn-telemetry = exfil (XTEA), api-metrics = heartbeat (Feistel)
4. Search process memory dump for key candidates, correlate with cipher usage
5. Implement modified XTEA decrypt (key-dependent delta)
6. Compare sample_alpha and sample_beta to evaluate feature resilience
7. Design family-level YARA detection rule anchored on resilient indicators
"""

import subprocess
import struct
import json
import sys

# ==================================================================
# Step 1: Extract BOTH covert DNS channels from PCAP using tshark
# ==================================================================
print("[+] Extracting DNS queries from PCAP...")

result = subprocess.run(
    ['tshark', '-r', '/app/traffic_capture.pcap',
     '-Y', 'dns.qry.name contains "cdn-telemetry"',
     '-T', 'fields', '-e', 'dns.qry.name'],
    capture_output=True, text=True
)
if result.returncode != 0:
    print(f"[-] tshark error: {result.stderr}")
    sys.exit(1)

cdn_queries = {}
for line in result.stdout.strip().split('\n'):
    line = line.strip()
    if not line:
        continue
    subdomain = line.split('.cdn-telemetry.example.com')[0]
    parts = subdomain.split('-', 1)
    if len(parts) == 2:
        try:
            seq = int(parts[0])
            data = parts[1]
            cdn_queries[seq] = data
        except ValueError:
            continue

result2 = subprocess.run(
    ['tshark', '-r', '/app/traffic_capture.pcap',
     '-Y', 'dns.qry.name contains "api-metrics"',
     '-T', 'fields', '-e', 'dns.qry.name'],
    capture_output=True, text=True
)

api_queries = {}
for line in result2.stdout.strip().split('\n'):
    line = line.strip()
    if not line:
        continue
    subdomain = line.split('.api-metrics.example.com')[0]
    parts = subdomain.split('-', 1)
    if len(parts) == 2:
        try:
            seq = int(parts[0])
            data = parts[1]
            api_queries[seq] = data
        except ValueError:
            continue

cdn_encoded = ''.join(cdn_queries[k] for k in sorted(cdn_queries.keys()))
api_encoded = ''.join(api_queries[k] for k in sorted(api_queries.keys()))

print(f"[+] cdn-telemetry: {len(cdn_queries)} unique queries, {len(cdn_encoded)} base32 chars")
print(f"[+] api-metrics: {len(api_queries)} unique queries, {len(api_encoded)} base32 chars")

# ==================================================================
# Step 2: Evaluate channels — cdn-telemetry has more data (exfil),
# api-metrics has less data (heartbeat). Binary analysis confirms:
# dns_send() uses transform_block (XTEA) and sends to cdn-telemetry
# dns_heartbeat() uses feistel_enc and sends to api-metrics
# ==================================================================
print("[+] Evaluating channels...")
print(f"[+] cdn-telemetry payload size: {len(cdn_encoded)} chars (larger = likely exfil)")
print(f"[+] api-metrics payload size: {len(api_encoded)} chars (smaller = likely heartbeat)")

# ==================================================================
# Step 3: Base32 decode the exfil channel (cdn-telemetry)
# ==================================================================
B32 = "abcdefghijklmnopqrstuvwxyz234567"

def base32_decode(s):
    bits = 0
    acc = 0
    out = bytearray()
    for c in s:
        if c not in B32:
            continue
        acc = (acc << 5) | B32.index(c)
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
            acc &= (1 << bits) - 1
    return bytes(out)

ciphertext = base32_decode(cdn_encoded)
print(f"[+] Ciphertext from cdn-telemetry: {len(ciphertext)} bytes")

# ==================================================================
# Step 4: Extract XTEA key from process memory dump
# ==================================================================
print("[+] Searching memory dump for session key...")
with open('/app/process_memory.bin', 'rb') as f:
    mem = f.read()

sess_offset = mem.find(b'SESS')
if sess_offset == -1:
    print("[-] SESS marker not found in memory dump")
    sys.exit(1)

key_offset = sess_offset + 12
key_bytes = mem[key_offset:key_offset + 16]
key = list(struct.unpack('<IIII', key_bytes))
print(f"[+] Session key at 0x{key_offset:04x}: {[hex(k) for k in key]}")

decoy_key = list(struct.unpack('<IIII', mem[0x1400:0x1410]))
print(f"[+] Decoy key at 0x1400: {[hex(k) for k in decoy_key]} (not used)")

config_key = list(struct.unpack('<IIII', mem[0x2000:0x2010]))
print(f"[+] Config key at 0x2000: {[hex(k) for k in config_key]} (Feistel/heartbeat)")

# ==================================================================
# Step 5: Modified XTEA decryption
# ==================================================================
def xtea_decrypt_block(v0, v1, key, rounds=32):
    delta = (key[0] ^ key[2]) | 0x80000001
    delta &= 0xFFFFFFFF
    sum_val = (delta * rounds) & 0xFFFFFFFF
    m = 0xFFFFFFFF
    for _ in range(rounds):
        v1 = (v1 - ((((v0 << 4) ^ (v0 >> 5)) + v0) ^ (sum_val + key[(sum_val >> 11) & 3]))) & m
        sum_val = (sum_val - delta) & m
        v0 = (v0 - ((((v1 << 4) ^ (v1 >> 5)) + v1) ^ (sum_val + key[sum_val & 3]))) & m
    return v0, v1

delta = (key[0] ^ key[2]) | 0x80000001
delta_hex = hex(delta & 0xFFFFFFFF)
print(f"[+] Computed XTEA delta: {delta_hex}")

plaintext = bytearray()
for i in range(0, len(ciphertext), 8):
    if i + 8 > len(ciphertext):
        break
    v0, v1 = struct.unpack('<II', ciphertext[i:i+8])
    d0, d1 = xtea_decrypt_block(v0, v1, key)
    plaintext.extend(struct.pack('<II', d0, d1))

plaintext = plaintext.rstrip(b'\x00')

# ==================================================================
# Step 6: Write recovered data
# ==================================================================
try:
    result_text = plaintext.decode('utf-8')
except UnicodeDecodeError:
    print("[-] Decryption produced non-UTF8 data")
    sys.exit(1)

print(f"[+] Recovered plaintext ({len(result_text)} bytes): {result_text}")

with open('/app/recovered_data.txt', 'w') as f:
    f.write(result_text)
print("[+] Written to /app/recovered_data.txt")

# ==================================================================
# Step 7: Write forensic analysis report
# ==================================================================
report = {
    "exfil_domain": "cdn-telemetry.example.com",
    "exfil_cipher": "modified-xtea",
    "other_domain": "api-metrics.example.com",
    "other_cipher": "feistel",
    "exfil_cipher_param_hex": delta_hex,
}

with open('/app/analysis_report.json', 'w') as f:
    json.dump(report, f, indent=2)
print("[+] Written analysis report to /app/analysis_report.json")

# ==================================================================
# Step 8: Compare both samples for detection assessment
# ==================================================================
print("[+] Comparing sample_alpha and sample_beta for family indicators...")

alpha_strings = subprocess.run(
    ['strings', '-n', '6', '/app/sample_alpha'],
    capture_output=True, text=True
).stdout.splitlines()

beta_strings = subprocess.run(
    ['strings', '-n', '6', '/app/sample_beta'],
    capture_output=True, text=True
).stdout.splitlines()

alpha_set = set(alpha_strings)
beta_set = set(beta_strings)
common = alpha_set & beta_set
only_alpha = alpha_set - beta_set
only_beta = beta_set - alpha_set

print(f"[+] Common strings: {len(common)}")
print(f"[+] Alpha-only strings: {len(only_alpha)}")
print(f"[+] Beta-only strings: {len(only_beta)}")

print("[+] Key common strings (resilient indicators):")
for s in sorted(common):
    if len(s) > 10:
        print(f"    {s}")

print("[+] Key differing strings (brittle indicators):")
for s in sorted(only_alpha):
    if len(s) > 10 and ('example' in s or 'monitor' in s or 'session' in s or 'netmond' in s):
        print(f"    alpha: {s}")
for s in sorted(only_beta):
    if len(s) > 10 and ('example' in s or 'syslog' in s or 'session' in s or 'netmond' in s):
        print(f"    beta:  {s}")

# ==================================================================
# Step 9: Write detection assessment
# ==================================================================
assessment = {
    "resilient_indicators": [
        {
            "feature": "Base32 encoding alphabet (abcdefghijklmnopqrstuvwxyz234567)",
            "reason": "Custom encoding table is compiled into the binary data segment and identical across both samples — structural to the DNS tunneling mechanism, not operationally configurable"
        },
        {
            "feature": "Heartbeat format string (UP:%s:%u:%u:%u)",
            "reason": "The printf format for operational status messages is hardcoded in both samples, indicating a shared codebase with a fixed heartbeat protocol"
        },
        {
            "feature": "Log message strings (config integrity failure, diagnostic complete)",
            "reason": "Internal logging strings are identical across variants, reflecting shared source code rather than operator configuration"
        },
        {
            "feature": "Dual-cipher architecture (Feistel + modified XTEA with key-dependent delta)",
            "reason": "Both samples implement the same two cipher algorithms with identical round counts and key scheduling — this is the core of the implant family design"
        }
    ],
    "brittle_indicators": [
        {
            "feature": "C2 server and exfiltration DNS infrastructure",
            "reason": "Command-and-control domain names are operationally configured per deployment — sample_alpha uses cdn-telemetry.example.com and api-metrics.example.com while sample_beta uses entirely different domains"
        },
        {
            "feature": "Version string and session seed parameters",
            "reason": "The version identifier and key derivation seed vary between builds, likely changed per campaign or target environment to avoid correlation"
        },
        {
            "feature": "Internal configuration server hostname",
            "reason": "Configuration server names are specific to each target environment and change across deployments"
        }
    ]
}

with open('/app/detection_assessment.json', 'w') as f:
    json.dump(assessment, f, indent=2)
print("[+] Written detection assessment to /app/detection_assessment.json")

# ==================================================================
# Step 10: Create family-level YARA detection rule
# ==================================================================
yara_rule = r'''rule implant_netmond_family {
    meta:
        description = "Detects netmond implant family - dual DNS channel exfiltration tool"
        author = "IR-2024-0847"

    strings:
        $b32_alphabet = "abcdefghijklmnopqrstuvwxyz234567"
        $heartbeat_fmt = "UP:%s:%u:%u:%u"
        $cfg_fail = "config integrity failure"
        $diag_done = "diagnostic complete"
        $usage = "Usage: %s <target-path>"

    condition:
        uint32(0) == 0x464C457F and
        $b32_alphabet and
        $heartbeat_fmt and
        2 of ($cfg_fail, $diag_done, $usage)
}
'''

with open('/app/implant.yar', 'w') as f:
    f.write(yara_rule)
print("[+] Written YARA rule to /app/implant.yar")

for sample in ['sample_alpha', 'sample_beta']:
    validate = subprocess.run(
        ['yara', '/app/implant.yar', f'/app/{sample}'],
        capture_output=True, text=True
    )
    if validate.returncode == 0 and validate.stdout.strip():
        print(f"[+] YARA validated: matches {sample}")
    else:
        print(f"[-] YARA issue with {sample}: {validate.stderr}")

validate_ls = subprocess.run(
    ['yara', '/app/implant.yar', '/usr/bin/ls'],
    capture_output=True, text=True
)
if validate_ls.returncode == 0 and not validate_ls.stdout.strip():
    print("[+] YARA validated: no false positive on /usr/bin/ls")
else:
    print(f"[-] YARA false positive issue: {validate_ls.stdout}")

print("[+] Solution complete")
