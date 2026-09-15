#!/usr/bin/env python3
"""
Forensic decryption solver — three deliverables:
1. Decrypt exfiltrated data → /app/flag.txt
2. Evaluate spec-vs-implementation discrepancies → /app/vuln_assessment.json
3. Create forged ciphertext proving key recovery → /app/forged_payload.bin
"""
import subprocess
import struct
import json


def icbrt(n):
    """Integer cube root via Newton's method for arbitrary precision."""
    if n <= 0:
        return 0
    x = 1 << ((n.bit_length() + 2) // 3)
    while True:
        y = (2 * x + n // (x * x)) // 3
        if y >= x:
            return x
        x = y


XTEA_DELTA = 0x9E3779B9
XTEA_ROUNDS = 32
MASK32 = 0xFFFFFFFF


def xtea_decrypt_block(v0, v1, key):
    """Decrypt one 8-byte XTEA block. key = [uint32 x4]."""
    s = (XTEA_DELTA * XTEA_ROUNDS) & MASK32
    for _ in range(XTEA_ROUNDS):
        v1 = (v1 - ((((v0 << 4) ^ (v0 >> 5)) + v0)
              ^ (s + key[(s >> 11) & 3]))) & MASK32
        s = (s - XTEA_DELTA) & MASK32
        v0 = (v0 - ((((v1 << 4) ^ (v1 >> 5)) + v1)
              ^ (s + key[s & 3]))) & MASK32
    return v0, v1


def xtea_encrypt_block(v0, v1, key):
    """Encrypt one 8-byte XTEA block. key = [uint32 x4]."""
    s = 0
    for _ in range(XTEA_ROUNDS):
        v0 = (v0 + ((((v1 << 4) ^ (v1 >> 5)) + v1)
              ^ (s + key[s & 3]))) & MASK32
        s = (s + XTEA_DELTA) & MASK32
        v1 = (v1 + ((((v0 << 4) ^ (v0 >> 5)) + v0)
              ^ (s + key[(s >> 11) & 3]))) & MASK32
    return v0, v1


def xor8(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def main():
    findings = {}  # Collect evidence for the vulnerability assessment

    # ================================================================
    # Phase 1: Binary analysis — identify actual cipher
    # ================================================================
    print("=" * 60)
    print("PHASE 1: Binary reverse engineering")
    print("=" * 60)

    r = subprocess.run(['strings', '/app/crypto_engine.so'],
                       capture_output=True, text=True)
    id_strings = [s for s in r.stdout.splitlines()
                  if any(k in s for k in ['AES', 'Enhanced', 'cipher', '3.1'])]
    print(f"Strings in .so: {id_strings}")
    findings['claimed_cipher'] = 'AES-256-Enhanced'

    r = subprocess.run(['nm', '-D', '/app/crypto_engine.so'],
                       capture_output=True, text=True)
    exports = [l.split()[-1] for l in r.stdout.splitlines() if ' T ' in l]
    print(f"Exported functions: {exports}")

    r = subprocess.run(['objdump', '-d', '/app/crypto_engine.so'],
                       capture_output=True, text=True)
    disasm = r.stdout

    xtea_confirmed = '9e3779b9' in disasm.lower()
    if xtea_confirmed:
        print("FINDING: XTEA delta constant 0x9E3779B9 found in disassembly")
        print("CONCLUSION: Cipher is XTEA, NOT AES-256 as strings claim")
        findings['actual_cipher'] = 'XTEA'
    else:
        print("WARNING: XTEA constant not found")
        findings['actual_cipher'] = 'unknown'

    r = subprocess.run(['readelf', '-h', '/app/crypto_engine.so'],
                       capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if 'Class:' in line or 'Machine:' in line:
            print(f"  {line.strip()}")

    # Check block size from cipher_get_block_size symbol
    findings['actual_block_size'] = 8  # From BLOCK_SIZE define in disassembly

    # ================================================================
    # Phase 2: Source code analysis — identify RSA weaknesses
    # ================================================================
    print()
    print("=" * 60)
    print("PHASE 2: Source code analysis")
    print("=" * 60)

    with open('/app/protocol.py') as f:
        proto_src = f.read()

    if 'pow(_I(M),self._e,self._n)' in proto_src or 'pow(' in proto_src:
        print("FINDING: RSA uses raw pow(M, e, n) — no OAEP padding")
        findings['rsa_padding'] = 'textbook (raw)'
    else:
        findings['rsa_padding'] = 'unknown'

    if 'os.urandom(16)' in proto_src:
        # Key generation: K = os.urandom(16) → 16-byte key, not 32
        print("FINDING: Session key is 16 bytes, not 32 as spec claims")
        findings['actual_key_size'] = 16

    # Read spec for comparison
    with open('/app/PROTOCOL_SPEC.md') as f:
        spec = f.read()
    findings['spec_cipher'] = 'AES-256'
    findings['spec_rsa_padding'] = 'OAEP (PKCS#1 v2.1)'
    findings['spec_rsa_key_size'] = 4096
    findings['spec_block_size'] = 16
    findings['spec_key_size'] = 32
    findings['spec_iv_size'] = 16

    # ================================================================
    # Phase 3: Network forensics — extract handshake from PCAP
    # ================================================================
    print()
    print("=" * 60)
    print("PHASE 3: Network forensics (tshark)")
    print("=" * 60)

    r = subprocess.run(
        ['tshark', '-r', '/app/session.pcap', '-T', 'fields',
         '-e', 'ip.src', '-e', 'ip.dst', '-e', 'udp.srcport',
         '-e', 'udp.dstport', '-e', 'frame.len'],
        capture_output=True, text=True)
    print("All packets:")
    for line in r.stdout.strip().split('\n'):
        print(f"  {line}")

    r = subprocess.run(
        ['tshark', '-r', '/app/session.pcap', '-T', 'fields',
         '-e', 'udp.payload', '-Y', 'udp.port == 9999'],
        capture_output=True, text=True)

    lines = [l.strip() for l in r.stdout.strip().split('\n') if l.strip()]
    print(f"\nProtocol packets on port 9999: {len(lines)}")

    payloads = []
    for line in lines:
        raw = bytes.fromhex(line.replace(':', ''))
        payloads.append(raw)

    messages = {}
    for p in payloads:
        if len(p) >= 6 and p[:4] == b'PROT' and p[4] == 0x02:
            msg_type = p[5]
            messages[msg_type] = p[6:]
            print(f"  MsgType 0x{msg_type:02x}: {len(p[6:])} bytes payload")

    sh = messages[0x02]
    selected_mode = sh[0]
    iv = sh[1:9]  # 8 bytes, not 16 as spec claims
    print(f"\nServerHello:")
    print(f"  Selected mode: {selected_mode}")
    print(f"  IV (8 bytes): {iv.hex()}")
    findings['actual_iv_size'] = 8

    ke = messages[0x03]
    rsa_ct_len = struct.unpack('>H', ke[:2])[0]
    rsa_ct_bytes = ke[2:2 + rsa_ct_len]
    C_rsa = int.from_bytes(rsa_ct_bytes, 'big')
    print(f"\nKeyExchange:")
    print(f"  RSA ciphertext: {rsa_ct_len} bytes ({C_rsa.bit_length()} bits)")

    encrypted_payload = messages[0x04]
    print(f"\nDataTransfer:")
    print(f"  Encrypted payload: {len(encrypted_payload)} bytes "
          f"({len(encrypted_payload) // 8} blocks)")

    # ================================================================
    # Phase 4: Evaluate spec vs reality — build assessment
    # ================================================================
    print()
    print("=" * 60)
    print("PHASE 4: Specification discrepancy evaluation")
    print("=" * 60)

    with open('/app/key_params.json') as f:
        pk = json.load(f)
    n_rsa = int(pk['n'], 16)
    e_rsa = pk['e']
    findings['actual_rsa_key_size'] = n_rsa.bit_length()
    findings['rsa_exponent'] = e_rsa

    print(f"RSA parameters: e={e_rsa}, n={n_rsa.bit_length()} bits")
    print()

    # Evaluate each discrepancy
    discrepancies = []

    # 1. Cipher algorithm
    d1_exploitable = True  # Must know it's XTEA to decrypt correctly
    d1_severity = "critical"
    print(f"[1] Cipher: spec=AES-256, actual=XTEA → exploitable={d1_exploitable}, severity={d1_severity}")
    print("    Rationale: Completely different algorithm. Without identifying XTEA via the")
    print("    0x9E3779B9 delta constant, decryption is impossible. The misleading strings")
    print("    ('AES-256-Enhanced') are deliberate misdirection.")
    discrepancies.append({
        "id": "cipher_algorithm",
        "spec_claim": "AES-256 block cipher (NIST SP 800-38A compliant, FIPS 197)",
        "actual_behavior": "XTEA block cipher (identified by delta constant 0x9E3779B9 in disassembly, 64-bit Feistel network)",
        "exploitable": True,
        "severity": "critical",
        "impact": "The actual cipher is completely different from the specification. Without identifying XTEA through binary analysis, any decryption attempt using AES will fail entirely. The misleading 'AES-256-Enhanced' strings and AES S-box fragments in the binary are deliberate misdirection."
    })

    # 2. RSA padding
    d2_exploitable = True  # Raw RSA + e=3 enables cube root attack
    d2_severity = "critical"
    print(f"[2] RSA padding: spec=OAEP, actual=textbook → exploitable={d2_exploitable}, severity={d2_severity}")
    print("    Rationale: OAEP would randomize and expand the plaintext, preventing cube root")
    print("    attack. Raw pow(M,e,n) with e=3 and small M enables trivial key recovery.")
    discrepancies.append({
        "id": "rsa_padding",
        "spec_claim": "RSA-OAEP key encapsulation (PKCS#1 v2.1 compliant)",
        "actual_behavior": "Textbook RSA — raw modular exponentiation pow(M, e, n) with no padding scheme",
        "exploitable": True,
        "severity": "critical",
        "impact": "Without OAEP padding, the RSA encryption is deterministic and mathematically attackable. Combined with the small public exponent e=3, the plaintext M (32 bytes = 256 bits) yields M^3 = 768 bits, which is far smaller than the 2048-bit modulus n. This means C = M^3 with no modular reduction, enabling a trivial integer cube root attack to recover the session key without factoring n."
    })

    # 3. RSA key size
    d3_exploitable = False  # 2048 bits is still infeasible to factor
    d3_severity = "high"
    print(f"[3] RSA key size: spec=4096, actual=2048 → exploitable={d3_exploitable}, severity={d3_severity}")
    print("    Rationale: 2048-bit RSA is not directly factorable with current technology.")
    print("    The breach used the cube root attack, not factoring. But the reduced size")
    print("    lowers the safety margin against future advances.")
    discrepancies.append({
        "id": "rsa_key_size",
        "spec_claim": "RSA-4096 (4096-bit modulus)",
        "actual_behavior": "RSA-2048 (2048-bit modulus, verified from key_params.json)",
        "exploitable": False,
        "severity": "high",
        "impact": "Reduced RSA key size from 4096 to 2048 bits halves the security margin against factoring attacks. While 2048-bit RSA is not directly factorable with current technology, it provides less headroom against quantum and algorithmic advances. In this specific attack, key recovery used the cube root method (not factoring), so this discrepancy was not directly exploited."
    })

    # 4. Symmetric key size
    d4_exploitable = False  # 128-bit brute force is infeasible; M^3 < n regardless
    d4_severity = "high"
    print(f"[4] Key size: spec=32 bytes, actual=16 bytes → exploitable={d4_exploitable}, severity={d4_severity}")
    print("    Rationale: Even with 32-byte keys, M = PREFIX(16)+K(32) = 48 bytes = 384 bits,")
    print("    M^3 = 1152 bits < 2048 bits, so the cube root attack would still succeed.")
    print("    The reduced key size is a general security concern but not the attack vector here.")
    discrepancies.append({
        "id": "symmetric_key_size",
        "spec_claim": "32-byte (256-bit) AES session key",
        "actual_behavior": "16-byte (128-bit) XTEA session key (observed in protocol.py: os.urandom(16))",
        "exploitable": False,
        "severity": "high",
        "impact": "Reduced symmetric key from 256 to 128 bits. While 128-bit keys are computationally infeasible to brute-force, this halves the security margin. Note: even with a 32-byte key, the cube root attack would still succeed because M = PREFIX(16) + K(32) = 384 bits, and 384^3 = 1152 bits < 2048-bit modulus. The key size reduction did not enable this specific attack."
    })

    # 5. Block size
    d5_exploitable = False  # Smaller blocks don't enable this attack
    d5_severity = "medium"
    print(f"[5] Block size: spec=16, actual=8 → exploitable={d5_exploitable}, severity={d5_severity}")
    print("    Rationale: 64-bit blocks are vulnerable to birthday attacks (Sweet32) after")
    print("    ~2^32 blocks, but that's not the attack used here. The block size difference")
    print("    is a consequence of using XTEA rather than AES.")
    discrepancies.append({
        "id": "block_size",
        "spec_claim": "16-byte (128-bit) AES block size",
        "actual_behavior": "8-byte (64-bit) XTEA block size (confirmed from cipher_get_block_size and BLOCK_SIZE=8 in disassembly)",
        "exploitable": False,
        "severity": "medium",
        "impact": "64-bit blocks are theoretically vulnerable to birthday-bound attacks (Sweet32) after approximately 2^32 blocks of data under the same key. This is a structural consequence of using XTEA rather than AES. The exfiltrated data was far too small to be affected by birthday attacks, so this was not exploited."
    })

    # 6. IV size
    d6_exploitable = False  # Follows from block size, not independently exploited
    d6_severity = "low"
    print(f"[6] IV size: spec=16, actual=8 → exploitable={d6_exploitable}, severity={d6_severity}")
    print("    Rationale: IV matches the actual 8-byte block size, which is correct for XTEA.")
    print("    The spec's 16-byte IV claim is consistent with its (incorrect) AES documentation.")
    print("    Smaller IV space is not a factor in this attack.")
    discrepancies.append({
        "id": "iv_size",
        "spec_claim": "16-byte initialization vector (matching AES 128-bit block)",
        "actual_behavior": "8-byte initialization vector (matching XTEA 64-bit block, extracted from ServerHello)",
        "exploitable": False,
        "severity": "low",
        "impact": "IV size matches the actual 8-byte block size, which is internally consistent for XTEA. The discrepancy reflects the cascading effect of the cipher algorithm mismatch. Smaller IV space (2^64 vs 2^128) slightly increases nonce collision probability under repeated use but was not a factor in this attack."
    })

    # Write vulnerability assessment
    assessment = {"discrepancies": discrepancies}
    with open('/app/vuln_assessment.json', 'w') as f:
        json.dump(assessment, f, indent=2)
    print("\nVulnerability assessment written to /app/vuln_assessment.json")

    # ================================================================
    # Phase 5: RSA cube root attack — key recovery
    # ================================================================
    print()
    print("=" * 60)
    print("PHASE 5: RSA cube root attack")
    print("=" * 60)

    print(f"RSA parameters: e={e_rsa}, n={n_rsa.bit_length()} bits")
    print("Attack: e=3, M is only 256 bits, M^3 = 768 bits < n")
    print("Computing integer cube root...")

    M_int = icbrt(C_rsa)
    assert M_int ** 3 == C_rsa, "Cube root attack failed — not a perfect cube"
    print("  Cube root verified as exact")

    M_bytes = M_int.to_bytes((M_int.bit_length() + 7) // 8, 'big')
    prefix = b"PROTO_V2_SESSKEY"
    assert M_bytes[:len(prefix)] == prefix, "Unexpected prefix in recovered M"
    K = M_bytes[len(prefix):]
    print(f"  Recovered XTEA key: {K.hex()} ({len(K)} bytes)")

    key_words = [struct.unpack('<I', K[i*4:(i+1)*4])[0] for i in range(4)]

    # ================================================================
    # Phase 6: XTEA-PCBC decryption
    # ================================================================
    print()
    print("=" * 60)
    print("PHASE 6: XTEA-PCBC decryption")
    print("=" * 60)

    feedback = iv
    plaintext = b""
    for i in range(0, len(encrypted_payload), 8):
        ct_block = encrypted_payload[i:i+8]
        v0, v1 = struct.unpack('<II', ct_block)
        dv0, dv1 = xtea_decrypt_block(v0, v1, key_words)
        decrypted = struct.pack('<II', dv0, dv1)
        pt_block = xor8(decrypted, feedback)
        plaintext += pt_block
        feedback = xor8(pt_block, ct_block)

    pad_len = plaintext[-1]
    if 1 <= pad_len <= 8 and all(b == pad_len for b in plaintext[-pad_len:]):
        plaintext = plaintext[:-pad_len]

    flag = plaintext.decode('utf-8')
    print(f"Recovered flag: {flag}")

    with open('/app/flag.txt', 'w') as f:
        f.write(flag)
    print("Flag written to /app/flag.txt")

    # ================================================================
    # Phase 7: Forge payload — prove bidirectional cipher control
    # ================================================================
    print()
    print("=" * 60)
    print("PHASE 7: Forged payload creation")
    print("=" * 60)

    forge_pt = b"FORGED_BY_ANALYST"
    forge_iv = b'\x00' * 8
    forge_pad = 8 - (len(forge_pt) % 8)
    if forge_pad == 0:
        forge_pad = 8
    forge_padded = forge_pt + bytes([forge_pad] * forge_pad)
    print(f"Forging: '{forge_pt.decode()}' ({len(forge_pt)} bytes)")
    print(f"Padded to {len(forge_padded)} bytes, IV = all zeros")

    forge_ct = b""
    forge_fb = forge_iv
    for i in range(0, len(forge_padded), 8):
        block = forge_padded[i:i+8]
        xored = xor8(block, forge_fb)
        v0, v1 = struct.unpack('<II', xored)
        ev0, ev1 = xtea_encrypt_block(v0, v1, key_words)
        ct_block = struct.pack('<II', ev0, ev1)
        forge_ct += ct_block
        forge_fb = xor8(block, ct_block)

    with open('/app/forged_payload.bin', 'wb') as f:
        f.write(forge_ct)
    print(f"Forged ciphertext: {forge_ct.hex()} ({len(forge_ct)} bytes)")
    print("Written to /app/forged_payload.bin")

    # Verify by decrypting
    verify_dec = b""
    verify_fb = forge_iv
    for i in range(0, len(forge_ct), 8):
        ct_block = forge_ct[i:i+8]
        v0, v1 = struct.unpack('<II', ct_block)
        dv0, dv1 = xtea_decrypt_block(v0, v1, key_words)
        decrypted = struct.pack('<II', dv0, dv1)
        pt_block = xor8(decrypted, verify_fb)
        verify_dec += pt_block
        verify_fb = xor8(pt_block, ct_block)
    verify_dec = verify_dec[:-verify_dec[-1]]
    print(f"Verification decrypt: {verify_dec.decode()}")
    assert verify_dec == forge_pt, "Forged payload verification failed"

    print()
    print("=" * 60)
    print("ALL DELIVERABLES COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    main()
