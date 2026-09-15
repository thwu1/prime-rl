#!/usr/bin/env python3
"""
Solution for APT Implant Forensics: Cipher Evaluation, Detection Tool, and Key Recovery.

This solver:
1. Parses the pcap to determine chunk ordering
2. Creates a reusable exfiltration detection tool
3. Extracts session and key data from the SQLite database
4. Evaluates both cipher engines to determine which was actually used
5. Evaluates the security properties of both engines
6. Identifies corrupted auth_token bytes and brute-forces them
   using known-plaintext constraints
7. Implements the inverse stream cipher to decrypt the document
8. Writes analysis.json, exfil_detector.py, decrypted_doc.txt, and answer.txt
"""

import hashlib
import sqlite3
import base64
import struct
import subprocess
import json

# ============================================================
# Step 1: Parse the pcap to extract exfil packet ordering
# ============================================================


def parse_pcap_native(filepath):
    """Parse pcap file directly to extract UDP payloads to port 8443."""
    payloads = []
    with open(filepath, 'rb') as f:
        ghdr = f.read(24)
        if len(ghdr) < 24:
            return payloads
        magic = struct.unpack('<I', ghdr[:4])[0]
        if magic != 0xa1b2c3d4:
            return payloads

        while True:
            phdr = f.read(16)
            if len(phdr) < 16:
                break
            _, _, incl_len, _ = struct.unpack('<IIII', phdr)
            pkt = f.read(incl_len)
            if len(pkt) < incl_len:
                break

            if len(pkt) < 42:
                continue
            ethertype = struct.unpack('>H', pkt[12:14])[0]
            if ethertype != 0x0800:
                continue
            ip_ihl = (pkt[14] & 0x0F) * 4
            protocol = pkt[23]
            if protocol != 17:  # UDP
                continue
            udp_off = 14 + ip_ihl
            if len(pkt) < udp_off + 8:
                continue
            dst_port = struct.unpack('>H', pkt[udp_off + 2: udp_off + 4])[0]
            if dst_port != 8443:
                continue
            payload = pkt[udp_off + 8:]
            payloads.append(payload)

    return payloads


def parse_pcap_tshark(filepath):
    """Use tshark to extract UDP payloads destined for port 8443."""
    for field in ['data.data', 'udp.payload']:
        result = subprocess.run(
            ['tshark', '-r', filepath,
             '-Y', 'udp.dstport == 8443',
             '-T', 'fields', '-e', field],
            capture_output=True, text=True
        )
        lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
        if lines:
            payloads = []
            for line in lines:
                hex_data = line.replace(':', '')
                payloads.append(bytes.fromhex(hex_data))
            return payloads
    return []


# Try tshark first, fall back to native parser
payloads = parse_pcap_tshark('/app/exfil_traffic.pcap')
if not payloads:
    print("[*] tshark extraction failed, using native pcap parser")
    payloads = parse_pcap_native('/app/exfil_traffic.pcap')

# Extract sequence numbers and chunk data from exfil protocol
# Filter by magic 0xC0DE0001 to exclude keepalive probes (0xBEEF0002)
chunks_with_seq = []
for payload in payloads:
    if len(payload) < 8:
        continue
    magic = struct.unpack('>I', payload[:4])[0]
    if magic != 0xC0DE0001:
        continue
    seq = struct.unpack('>I', payload[4:8])[0]
    chunk_data = payload[8:]
    chunks_with_seq.append((seq, chunk_data))

# Sort by sequence number and concatenate
chunks_with_seq.sort(key=lambda x: x[0])
ciphertext = b''.join(data for _, data in chunks_with_seq)

print(f"[+] Extracted {len(chunks_with_seq)} chunks from pcap")
print(f"[+] Ciphertext: {len(ciphertext)} bytes")

# ============================================================
# Step 2: Create exfiltration detection tool
# ============================================================

detector_code = r'''#!/usr/bin/env python3
"""Exfiltration detector for APT implant custom binary protocol.
Identifies exfil packets by protocol magic 0xC0DE0001, filtering out
keepalive probes (magic 0xBEEF0002) and other traffic on the same port."""
import struct
import json
import sys

EXFIL_MAGIC = 0xC0DE0001

def detect_exfil(pcap_path):
    packets = []
    with open(pcap_path, 'rb') as f:
        ghdr = f.read(24)
        if len(ghdr) < 24:
            return packets
        magic = struct.unpack('<I', ghdr[:4])[0]
        if magic != 0xa1b2c3d4:
            return packets
        while True:
            phdr = f.read(16)
            if len(phdr) < 16:
                break
            _, _, incl_len, _ = struct.unpack('<IIII', phdr)
            pkt = f.read(incl_len)
            if len(pkt) < incl_len:
                break
            if len(pkt) < 42:
                continue
            ethertype = struct.unpack('>H', pkt[12:14])[0]
            if ethertype != 0x0800:
                continue
            protocol = pkt[23]
            if protocol != 17:
                continue
            ip_ihl = (pkt[14] & 0x0F) * 4
            udp_off = 14 + ip_ihl
            if len(pkt) < udp_off + 8:
                continue
            dst_port = struct.unpack('>H', pkt[udp_off + 2: udp_off + 4])[0]
            if dst_port != 8443:
                continue
            payload = pkt[udp_off + 8:]
            if len(payload) < 8:
                continue
            pkt_magic = struct.unpack('>I', payload[:4])[0]
            if pkt_magic != EXFIL_MAGIC:
                continue
            seq = struct.unpack('>I', payload[4:8])[0]
            data_len = len(payload) - 8
            packets.append({"seq": seq, "payload_size": data_len})
    return packets

if __name__ == "__main__":
    pcap_path = sys.argv[1]
    packets = detect_exfil(pcap_path)
    result = {
        "exfil_packet_count": len(packets),
        "sequence_numbers": sorted(p["seq"] for p in packets),
        "total_payload_bytes": sum(p["payload_size"] for p in packets)
    }
    print(json.dumps(result))
'''

with open("/app/exfil_detector.py", "w") as f:
    f.write(detector_code)
print("[+] Created /app/exfil_detector.py")

# ============================================================
# Step 3: Extract key material from SQLite database
# ============================================================

db = sqlite3.connect("/app/implant.db")
db.row_factory = sqlite3.Row

config = {}
for row in db.execute("SELECT key, value FROM config"):
    config[row["key"]] = row["value"]

fragments = {}
for row in db.execute("SELECT fragment_type, fragment_data FROM key_fragments"):
    fragments[row["fragment_type"]] = row["fragment_data"]

# Get all sessions — use explicit dict comprehension for reliable Row-to-dict
all_sessions = []
for row in db.execute("SELECT * FROM sessions"):
    all_sessions.append({k: row[k] for k in row.keys()})

db.close()

# Find active session
active_session = None
for s in all_sessions:
    if s["status"] == "active":
        active_session = s
        break

assert active_session is not None, "No active session found"

print(f"[+] Node ID: {config['node_id']}")
print(f"[+] Active session: {active_session['session_id']}")
print(f"[+] Active enc_mode: {active_session.get('enc_mode', 'N/A')}")
print(f"[+] Data integrity: {active_session.get('data_integrity', 'N/A')}")
print(f"[+] Fragment types: {list(fragments.keys())}")

# ============================================================
# Step 4: Evaluate cipher engines
# ============================================================

KNOWN_HEADER = b"CLASSIFICATION: "  # Known first 16 bytes of plaintext
PHI = 0x9E3779B9
BLK = 256
FB = 16


def ksa(key):
    """Key Schedule Algorithm - matches se_init in libcrypto.so."""
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    return S


def compute_inv(S):
    """Compute inverse substitution table."""
    inv = [0] * 256
    for i in range(256):
        inv[S[i]] = i
    return inv


def decrypt_se(ct_bytes, key, tweak, max_bytes=None):
    """Decrypt using stream engine (inverse of se_transform)."""
    S = ksa(key)
    inv_S = compute_inv(S)
    n = len(ct_bytes) if max_bytes is None else min(max_bytes, len(ct_bytes))
    pt = bytearray()
    for i in range(n):
        tb = tweak[i % len(tweak)]
        pb = ((i + 1) * PHI) & 0xFF
        sb = ct_bytes[i] ^ tb ^ pb
        pt.append(inv_S[sb])
        if (i + 1) % BLK == 0:
            fb_data = ct_bytes[max(0, i + 1 - FB): i + 1]
            j = 0
            for k in range(256):
                j = (j + S[k] + fb_data[k % len(fb_data)]) % 256
                S[k], S[j] = S[j], S[k]
            inv_S = compute_inv(S)
    return bytes(pt)


# Derive tweak from active session
tweak = hashlib.sha256(
    active_session["session_id"].encode("utf-8")
).digest()[:8]

# --- 4a: Test recovery engine (enc_mode says "recovery") ---
print("\n[*] Testing recovery engine (enc_mode='recovery')...")

# Recovery engine key derivation (matches re_init in libcrypto.so):
# Fold entropy_pool bytes into 16-byte key via XOR
entropy_raw = base64.b64decode(config.get('entropy_pool', ''))
re_key = bytearray(16)
for i, b in enumerate(entropy_raw):
    re_key[i % 16] ^= b

# Recovery engine transform: simple repeating-key XOR
re_decrypted_header = bytes(
    ciphertext[i] ^ re_key[i % 16] for i in range(min(16, len(ciphertext)))
)
re_match = re_decrypted_header == KNOWN_HEADER
print(f"[!] Recovery engine output: {re_decrypted_header}")
print(f"[!] Recovery engine header match: {re_match}")

# --- 4b: Test stream engine with stored (possibly corrupted) key ---
print("\n[*] Testing stream engine with stored auth_token...")

node_id = config["node_id"].encode("utf-8")
node_id_md5 = hashlib.md5(node_id).digest()[:8]
primary_raw = bytes.fromhex(fragments["primary"])
secondary_raw = base64.b64decode(fragments["secondary"])

stored_token = bytes.fromhex(active_session["auth_token"])
key_part1_stored = bytes(a ^ b for a, b in zip(primary_raw, stored_token[:8]))
key_part2 = bytes(a ^ b for a, b in zip(secondary_raw, node_id_md5))
stored_key = key_part1_stored + key_part2

se_test_header = decrypt_se(ciphertext, stored_key, tweak, max_bytes=16)
se_match = se_test_header == KNOWN_HEADER
print(f"[!] Stream engine output: {se_test_header}")
print(f"[!] Stream engine header match: {se_match}")

# ============================================================
# Step 5: Evaluate security properties of both engines
# ============================================================

print("\n[*] Evaluating cipher engine security properties...")

# Recovery engine (RE) analysis:
# re_transform: out[i] = in[i] ^ key[i % 16]
# This is simple repeating-key XOR. Given N known plaintext bytes at
# positions 0..N-1, each key byte k[i%16] = plaintext[i] ^ ciphertext[i].
# With 16 consecutive known bytes from position 0, ALL 16 key bytes are
# recovered: key[j] = pt[j] ^ ct[j] for j=0..15.
# This makes RE trivially vulnerable to known-plaintext attacks.
re_kpa_full_recovery = 16  # 16 consecutive bytes from pos 0

# Stream engine (SE) analysis:
# se_transform uses KSA (key-schedule algorithm) to build a 256-byte
# substitution table, then applies substitution + XOR with tweak + XOR
# with position-dependent PHI constant, plus periodic S-box refresh via
# ciphertext feedback. Key recovery requires inverting the KSA, which is
# computationally infeasible without brute-forcing the key space.
# SE is substantially more secure than RE.
weaker_engine = "re"

print(f"[+] RE: repeating-key XOR, full key recovery with {re_kpa_full_recovery} known-plaintext bytes")
print(f"[+] SE: KSA-based substitution with ciphertext feedback, infeasible to break without key")
print(f"[+] Weaker engine: {weaker_engine}")

# ============================================================
# Step 6: Key recovery via known-plaintext brute force
# ============================================================

if not se_match:
    print("\n[*] Stream engine failed with stored key - checking for corruption...")
    print(f"[*] data_integrity = '{active_session.get('data_integrity', 'N/A')}'")
    print(f"[*] Stored auth_token[:8]: {stored_token[:8].hex()}")

    # Identify zero bytes in the first 8 bytes (used for key derivation)
    # Zero bytes in otherwise random-looking data are likely corrupted
    zero_positions = [i for i in range(8) if stored_token[i] == 0x00]
    print(f"[*] Zero bytes at positions: {zero_positions}")

    if len(zero_positions) >= 2:
        print(f"[*] Brute-forcing {len(zero_positions)} corrupted byte(s)...")

        # Pre-compute the expected S-box output for position 0
        # For correct key: S[KNOWN_HEADER[0]] XOR tweak[0] XOR pv[0] = ciphertext[0]
        # So: S[KNOWN_HEADER[0]] = ciphertext[0] XOR tweak[0] XOR pv[0]
        pv0 = (1 * PHI) & 0xFF
        target_s_val = ciphertext[0] ^ tweak[0] ^ pv0

        found = False
        correct_token = None
        pos_a, pos_b = zero_positions[0], zero_positions[1]

        for a in range(256):
            if found:
                break
            for b in range(256):
                # Build candidate auth_token (first 8 bytes)
                candidate = bytearray(stored_token[:8])
                candidate[pos_a] = a
                candidate[pos_b] = b

                # Derive candidate key_part1
                kp1 = bytes(x ^ y for x, y in zip(primary_raw, candidate))
                candidate_key = kp1 + key_part2

                # Quick rejection: check S[0x43] after KSA
                S = ksa(candidate_key)
                if S[KNOWN_HEADER[0]] != target_s_val:
                    continue

                # Full 16-byte verification
                test_pt = decrypt_se(ciphertext, candidate_key, tweak, max_bytes=16)
                if test_pt == KNOWN_HEADER:
                    correct_token = bytearray(stored_token)
                    correct_token[pos_a] = a
                    correct_token[pos_b] = b
                    correct_token = bytes(correct_token)
                    print(f"[+] FOUND! byte[{pos_a}]=0x{a:02x}, byte[{pos_b}]=0x{b:02x}")
                    found = True
                    break

        if not found:
            # Fallback: try all pairs of positions in first 8 bytes
            print("[*] Zero-byte heuristic failed, trying all position pairs...")
            for pa in range(8):
                if found:
                    break
                for pb in range(pa + 1, 8):
                    if found:
                        break
                    for a in range(256):
                        if found:
                            break
                        for b in range(256):
                            candidate = bytearray(stored_token[:8])
                            candidate[pa] = a
                            candidate[pb] = b
                            kp1 = bytes(x ^ y for x, y in zip(primary_raw, candidate))
                            candidate_key = kp1 + key_part2
                            S = ksa(candidate_key)
                            if S[KNOWN_HEADER[0]] != target_s_val:
                                continue
                            test_pt = decrypt_se(
                                ciphertext, candidate_key, tweak, max_bytes=16
                            )
                            if test_pt == KNOWN_HEADER:
                                correct_token = bytearray(stored_token)
                                correct_token[pa] = a
                                correct_token[pb] = b
                                correct_token = bytes(correct_token)
                                zero_positions = [pa, pb]
                                print(f"[+] FOUND! positions [{pa},{pb}], "
                                      f"values [0x{a:02x},0x{b:02x}]")
                                found = True
                                break

        assert found, "Key recovery failed - could not find correct auth_token bytes"
    else:
        raise RuntimeError(
            "Key derivation failed but no obvious corrupted bytes found"
        )
else:
    correct_token = stored_token
    zero_positions = []

print(f"[+] Recovered auth_token: {correct_token.hex()}")

# ============================================================
# Step 7: Full decryption with recovered key
# ============================================================

recovered_kp1 = bytes(a ^ b for a, b in zip(primary_raw, correct_token[:8]))
recovered_key = recovered_kp1 + key_part2

plaintext = decrypt_se(ciphertext, recovered_key, tweak)

print(f"[+] Decrypted document: {len(plaintext)} bytes")
print(f"[+] Preview: {plaintext[:60].decode('utf-8', errors='replace')}")

# ============================================================
# Step 8: Write outputs
# ============================================================

# Analysis report with forensic evaluation and security assessment
analysis = {
    "cipher_engine": "se",
    "recovered_auth_token": correct_token.hex(),
    "corrupted_byte_positions": sorted(zero_positions),
    "weaker_engine": weaker_engine,
    "kpa_bytes_for_full_key_recovery": re_kpa_full_recovery,
}
with open("/app/analysis.json", "w") as f:
    json.dump(analysis, f, indent=2)

# Decrypted document
with open("/app/decrypted_doc.txt", "wb") as f:
    f.write(plaintext)

# SHA-256 hash
answer = hashlib.sha256(plaintext).hexdigest()
with open("/app/answer.txt", "w") as f:
    f.write(answer)

print(f"[+] SHA-256: {answer}")
print(f"[+] Analysis: {json.dumps(analysis)}")
print("[+] All outputs written successfully")
