#!/usr/bin/env python3

"""
Fix the XAES-256-GCM implementation and re-encrypt all records.

The bug is in /app/service/crypto.py in the CMAC subkey derivation:
When MSB_1(L) = 1, the code applies XOR with 0x87 BEFORE the left shift:
    K1 = ((L ^ 0x87) << 1) & mask   # WRONG
instead of AFTER:
    K1 = ((L << 1) & mask) ^ 0x87   # CORRECT per NIST SP 800-38B

This only affects keys where MSB_1(AES-256_K(0^128)) = 1, which is roughly
50% of keys, explaining the intermittent interoperability failures.
"""

import json
import os
import hmac
import hashlib
from Crypto.Cipher import AES


# ---- Correct XAES-256-GCM implementation ----

def _aes256_ecb(key, block):
    return AES.new(key, AES.MODE_ECB).encrypt(block)


def correct_derive_key(key, nonce):
    """CMAC-based KDF with correct order: shift first, then XOR."""
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


def correct_decrypt(key, nonce, ciphertext, aad):
    Kx, Nx = correct_derive_key(key, nonce)
    ct_body = ciphertext[:-16]
    tag = ciphertext[-16:]
    cipher = AES.new(Kx, AES.MODE_GCM, nonce=Nx)
    cipher.update(aad)
    return cipher.decrypt_and_verify(ct_body, tag)


# ---- Key derivation (same as keymanager.py) ----

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
    # Step 1: Write the corrected crypto.py
    fixed_source = '''\
"""XAES-256-GCM implementation for the data encryption service."""
from Crypto.Cipher import AES


def _aes256_ecb_encrypt(key, block):
    """Encrypt a single 16-byte block with AES-256 in ECB mode."""
    return AES.new(key, AES.MODE_ECB).encrypt(block)


def derive_key(key, nonce):
    """Derive XAES-256-GCM subkey and sub-nonce."""
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

    # Step 2: Load config and re-encrypt all records
    with open("/app/service/config.json") as f:
        config = json.load(f)
    master_key = bytes.fromhex(config["master_key_hex"])

    os.makedirs("/app/data/corrected", exist_ok=True)

    plaintext_dir = "/app/data/plaintext"
    encrypted_dir = "/app/data/encrypted"

    for fname in sorted(os.listdir(plaintext_dir)):
        if not fname.endswith(".json"):
            continue
        record_id = fname.replace(".json", "")

        # Read plaintext
        with open(os.path.join(plaintext_dir, fname), "rb") as f:
            plaintext_bytes = f.read()

        # Read original encrypted record to get nonce and aad
        with open(os.path.join(encrypted_dir, f"{record_id}.enc")) as f:
            enc_data = json.load(f)
        nonce = bytes.fromhex(enc_data["nonce_hex"])
        aad = enc_data["aad"]

        # Derive per-record key
        key = hkdf_sha256(master_key, SALT, record_id.encode())

        # Re-encrypt with correct implementation
        ciphertext = correct_encrypt(key, nonce, plaintext_bytes, aad.encode())

        # Write corrected record
        corrected_data = {
            "record_id": record_id,
            "nonce_hex": nonce.hex(),
            "aad": aad,
            "ciphertext_hex": ciphertext.hex(),
        }
        with open(os.path.join("/app/data/corrected", f"{record_id}.enc"), "w") as f:
            json.dump(corrected_data, f, indent=2)

    print("Re-encrypted all 30 records to /app/data/corrected/")


if __name__ == "__main__":
    main()
