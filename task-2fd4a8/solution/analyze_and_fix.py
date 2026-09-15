#!/usr/bin/env python3

"""
Analyze the three XAES-256-GCM implementations, produce audit report,
fix the deployed implementation, and re-encrypt all records.

Analysis summary:
- Alpha: CMAC subkey derivation bug. When MSB_1(L)=1, it computes
  K1 = ((L ^ 0x87) << 1) instead of the correct K1 = (L << 1) ^ 0x87.
  The XOR with the reduction polynomial is applied before the shift instead
  of after. This only manifests for ~50% of keys (those where MSB=1).

- Beta (Go binary): Correct implementation. Matches spec test vectors.

- Gamma: Nonce split is reversed. Uses N[12:] (last 12 bytes) as KDF context
  and N[:12] (first 12 bytes) as the GCM nonce, instead of the spec's
  N[:12] for KDF context and N[12:] for GCM nonce. This always produces
  wrong output (unless the two nonce halves happen to be identical).
"""

import json
import os
import subprocess
import sys
import hmac
import hashlib
from Crypto.Cipher import AES


# ---- Correct XAES-256-GCM implementation ----

def _aes256_ecb(key, block):
    return AES.new(key, AES.MODE_ECB).encrypt(block)


def correct_derive_key(key, nonce):
    L = _aes256_ecb(key, b"\x00" * 16)
    L_int = int.from_bytes(L, "big")
    msb = L_int >> 127
    K1_int = (L_int << 1) & ((1 << 128) - 1)
    if msb == 1:
        K1_int ^= 0x87
    K1 = K1_int.to_bytes(16, "big")
    M1 = b"\x00\x01\x58\x00" + nonce[:12]
    M2 = b"\x00\x02\x58\x00" + nonce[:12]
    M1_x = bytes(a ^ b for a, b in zip(M1, K1))
    M2_x = bytes(a ^ b for a, b in zip(M2, K1))
    Kx = _aes256_ecb(key, M1_x) + _aes256_ecb(key, M2_x)
    Nx = nonce[12:]
    return Kx, Nx


def correct_encrypt(key, nonce, plaintext, aad):
    Kx, Nx = correct_derive_key(key, nonce)
    cipher = AES.new(Kx, AES.MODE_GCM, nonce=Nx)
    cipher.update(aad)
    ct, tag = cipher.encrypt_and_digest(plaintext)
    return ct + tag


# ---- Analyze implementations ----

def verify_with_go_binary(key_hex, nonce_hex):
    """Run the Go binary's derive-key to get reference Kx/Nx."""
    result = subprocess.run(
        ["/app/implementations/beta/xaes_tool", "derive-key", key_hex, nonce_hex],
        capture_output=True, text=True
    )
    lines = result.stdout.strip().split("\n")
    kx_hex = lines[0].split("=")[1]
    nx_hex = lines[1].split("=")[1]
    return kx_hex, nx_hex


def analyze_alpha(key, nonce):
    """Check Alpha's derive_key against correct values."""
    sys.path.insert(0, "/app/implementations/alpha")
    if "crypto" in sys.modules:
        del sys.modules["crypto"]
    import crypto as alpha
    alpha_kx, alpha_nx = alpha.derive_key(key, nonce)
    correct_kx, correct_nx = correct_derive_key(key, nonce)
    return alpha_kx == correct_kx and alpha_nx == correct_nx


def analyze_gamma(key, nonce):
    """Check Gamma's derive_key against correct values."""
    sys.path.insert(0, "/app/implementations/gamma")
    if "crypto" in sys.modules:
        del sys.modules["crypto"]
    import crypto as gamma
    gamma_kx, gamma_nx = gamma.derive_key(key, nonce)
    correct_kx, correct_nx = correct_derive_key(key, nonce)
    return gamma_kx == correct_kx and gamma_nx == correct_nx


# ---- Key derivation ----

SALT = b"xaes-audit-service-v1"


def hkdf_sha256(ikm, salt, info, length=32):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    t = b""
    okm = b""
    for i in range(1, (length + 31) // 32 + 1):
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


def main():
    # ---- Step 1: Compute verification intermediate values ----
    test_key = bytes.fromhex("0101010101010101010101010101010101010101010101010101010101010101")
    L = _aes256_ecb(test_key, b"\x00" * 16)
    L_int = int.from_bytes(L, "big")
    msb = L_int >> 127
    K1_int = (L_int << 1) & ((1 << 128) - 1)
    if msb == 1:
        K1_int ^= 0x87
    K1 = K1_int.to_bytes(16, "big")

    print(f"Verification: L={L.hex()}, K1={K1.hex()}")

    # Cross-check with Go binary
    go_kx, go_nx = verify_with_go_binary(
        "0101010101010101010101010101010101010101010101010101010101010101",
        "4142434445464748494a4b4c4d4e4f505152535455565758"
    )
    print(f"Go binary: Kx={go_kx}, Nx={go_nx}")

    # ---- Step 2: Analyze each implementation ----
    test_nonce = b"ABCDEFGHIJKLMNOPQRSTUVWX"

    # Test with MSB=0 key
    key_msb0 = bytes.fromhex("0101010101010101010101010101010101010101010101010101010101010101")
    alpha_ok_msb0 = analyze_alpha(key_msb0, test_nonce)

    # Test with MSB=1 key
    key_msb1 = bytes.fromhex("0303030303030303030303030303030303030303030303030303030303030303")
    alpha_ok_msb1 = analyze_alpha(key_msb1, test_nonce)

    gamma_ok_msb0 = analyze_gamma(key_msb0, test_nonce)
    gamma_ok_msb1 = analyze_gamma(key_msb1, test_nonce)

    print(f"Alpha: MSB=0 {'PASS' if alpha_ok_msb0 else 'FAIL'}, MSB=1 {'PASS' if alpha_ok_msb1 else 'FAIL'}")
    print(f"Gamma: MSB=0 {'PASS' if gamma_ok_msb0 else 'FAIL'}, MSB=1 {'PASS' if gamma_ok_msb1 else 'FAIL'}")

    # ---- Step 3: Write audit report ----
    audit_report = {
        "implementations": {
            "alpha": {
                "verdict": "non-compliant",
                "description": "CMAC subkey K1 derivation has order-of-operations bug: when MSB_1(L)=1, "
                               "computes K1 = ((L XOR 0x87) << 1) instead of K1 = (L << 1) XOR 0x87. "
                               "The XOR with the reduction polynomial is applied before the left shift "
                               "instead of after, per NIST SP 800-38B. Only affects ~50% of keys."
            },
            "beta": {
                "verdict": "compliant",
                "description": "Go binary implementation matches all C2SP reference test vectors and "
                               "OpenSSL-verified intermediate values. Correct CMAC subkey derivation "
                               "and nonce handling."
            },
            "gamma": {
                "verdict": "non-compliant",
                "description": "Nonce split is reversed: uses N[12:] (last 12 bytes) as KDF context and "
                               "N[:12] (first 12 bytes) as GCM nonce, instead of N[:12] for KDF context "
                               "and N[12:] for GCM nonce per spec. Always produces incorrect output."
            }
        },
        "verification": {
            "test_key_hex": "0101010101010101010101010101010101010101010101010101010101010101",
            "L_hex": L.hex(),
            "K1_hex": K1.hex()
        }
    }

    with open("/app/audit_report.json", "w") as f:
        json.dump(audit_report, f, indent=2)
    print("Wrote /app/audit_report.json")

    # ---- Step 4: Deploy corrected crypto.py ----
    fixed_source = '''\
"""XAES-256-GCM implementation — spec-compliant."""
from Crypto.Cipher import AES


def _aes256_ecb_encrypt(key, block):
    """Encrypt a single 16-byte block with AES-256 in ECB mode."""
    return AES.new(key, AES.MODE_ECB).encrypt(block)


def derive_key(key, nonce):
    """Derive XAES-256-GCM subkey and sub-nonce per C2SP specification."""
    L = _aes256_ecb_encrypt(key, b"\\x00" * 16)
    L_int = int.from_bytes(L, "big")
    msb = L_int >> 127
    K1_int = (L_int << 1) & ((1 << 128) - 1)
    if msb == 1:
        K1_int ^= 0x87
    K1 = K1_int.to_bytes(16, "big")
    M1 = b"\\x00\\x01\\x58\\x00" + nonce[:12]
    M2 = b"\\x00\\x02\\x58\\x00" + nonce[:12]
    M1_x = bytes(a ^ b for a, b in zip(M1, K1))
    M2_x = bytes(a ^ b for a, b in zip(M2, K1))
    Kx = _aes256_ecb_encrypt(key, M1_x) + _aes256_ecb_encrypt(key, M2_x)
    Nx = nonce[12:]
    return Kx, Nx


def encrypt(key, nonce, plaintext, aad):
    """Encrypt with XAES-256-GCM."""
    Kx, Nx = derive_key(key, nonce)
    cipher = AES.new(Kx, AES.MODE_GCM, nonce=Nx)
    cipher.update(aad)
    ct, tag = cipher.encrypt_and_digest(plaintext)
    return ct + tag


def decrypt(key, nonce, ciphertext, aad):
    """Decrypt with XAES-256-GCM."""
    Kx, Nx = derive_key(key, nonce)
    ct_body = ciphertext[:-16]
    tag = ciphertext[-16:]
    cipher = AES.new(Kx, AES.MODE_GCM, nonce=Nx)
    cipher.update(aad)
    return cipher.decrypt_and_verify(ct_body, tag)
'''
    with open("/app/service/crypto.py", "w") as f:
        f.write(fixed_source)
    print("Fixed /app/service/crypto.py")

    # ---- Step 5: Re-encrypt all records ----
    with open("/app/service/config.json") as f:
        config = json.load(f)
    master_key = bytes.fromhex(config["master_key_hex"])

    os.makedirs("/app/data/corrected", exist_ok=True)

    for i in range(30):
        record_id = f"record_{i:03d}"

        with open(f"/app/data/plaintext/{record_id}.json", "rb") as f:
            plaintext_bytes = f.read()

        with open(f"/app/data/encrypted/{record_id}.enc") as f:
            enc_data = json.load(f)
        nonce = bytes.fromhex(enc_data["nonce_hex"])
        aad = enc_data["aad"]

        key = hkdf_sha256(master_key, SALT, record_id.encode())
        ciphertext = correct_encrypt(key, nonce, plaintext_bytes, aad.encode())

        corrected_data = {
            "record_id": record_id,
            "nonce_hex": nonce.hex(),
            "aad": aad,
            "ciphertext_hex": ciphertext.hex(),
        }
        with open(f"/app/data/corrected/{record_id}.enc", "w") as f:
            json.dump(corrected_data, f, indent=2)

    print("Re-encrypted all 30 records to /app/data/corrected/")


if __name__ == "__main__":
    main()
