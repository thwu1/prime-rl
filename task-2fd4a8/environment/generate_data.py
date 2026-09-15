#!/usr/bin/env python3
"""Generate test data and interoperability reports for the XAES-256-GCM audit task.

Creates plaintext records, encrypts them with Alpha's implementation,
generates cross-implementation interoperability matrix and partner reports.
"""
import json
import os
import hashlib
import hmac
import sys

sys.path.insert(0, "/app/implementations/alpha")
import crypto as alpha_crypto

del sys.modules["crypto"]
sys.path.insert(0, "/app/implementations/gamma")
import crypto as gamma_crypto

from Crypto.Cipher import AES as AES_raw

MASTER_KEY_HEX = "a1b2c3d4e5f6071829304a5b6c7d8e9fa1b2c3d4e5f6071829304a5b6c7d8e9f"
MASTER_KEY = bytes.fromhex(MASTER_KEY_HEX)
SALT = b"xaes-audit-service-v1"
NUM_RECORDS = 30


def hkdf_sha256(ikm, salt, info, length=32):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    t = b""
    okm = b""
    for j in range(1, (length + 31) // 32 + 1):
        t = hmac.new(prk, t + info + bytes([j]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


def generate_nonce(seed, index):
    return hashlib.shake_128(seed + index.to_bytes(4, "big")).digest(24)


# --- Reference correct implementation (for generating interop matrix) ---

def _ref_derive_key(key, nonce):
    L = AES_raw.new(key, AES_raw.MODE_ECB).encrypt(b"\x00" * 16)
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
    Kx = AES_raw.new(key, AES_raw.MODE_ECB).encrypt(M1_x) + AES_raw.new(key, AES_raw.MODE_ECB).encrypt(M2_x)
    Nx = nonce[12:]
    return Kx, Nx


def ref_encrypt(key, nonce, pt, aad):
    Kx, Nx = _ref_derive_key(key, nonce)
    cipher = AES_raw.new(Kx, AES_raw.MODE_GCM, nonce=Nx)
    cipher.update(aad)
    ct, tag = cipher.encrypt_and_digest(pt)
    return ct + tag


def ref_decrypt(key, nonce, ct, aad):
    Kx, Nx = _ref_derive_key(key, nonce)
    ct_body = ct[:-16]
    tag = ct[-16:]
    cipher = AES_raw.new(Kx, AES_raw.MODE_GCM, nonce=Nx)
    cipher.update(aad)
    return cipher.decrypt_and_verify(ct_body, tag)


def try_decrypt(decrypt_fn, key, nonce, ct_hex, aad):
    try:
        ct = bytes.fromhex(ct_hex)
        decrypt_fn(key, nonce, ct, aad)
        return "pass"
    except Exception:
        return "fail"


def main():
    os.makedirs("/app/data/plaintext", exist_ok=True)
    os.makedirs("/app/data/encrypted", exist_ok=True)
    os.makedirs("/app/data/reports", exist_ok=True)

    nonce_seed = hashlib.sha256(MASTER_KEY + b"nonce-generation").digest()

    # ---- Generate cross-implementation interop matrix ----

    interop_keys = [
        {"id": "test_1", "key_hex": "0101010101010101010101010101010101010101010101010101010101010101"},
        {"id": "test_2", "key_hex": "0303030303030303030303030303030303030303030303030303030303030303"},
        {"id": "test_3", "key_hex": "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"},
        {"id": "test_4", "key_hex": "4242424242424242424242424242424242424242424242424242424242424242"},
        {"id": "test_5", "key_hex": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"},
    ]
    interop_nonce = bytes.fromhex("4142434445464748494a4b4c4d4e4f505152535455565758")
    interop_pt = b"XAES-256-GCM"
    interop_aad = b""

    matrix_keys = []
    for tk in interop_keys:
        key = bytes.fromhex(tk["key_hex"])
        L = AES_raw.new(key, AES_raw.MODE_ECB).encrypt(b"\x00" * 16)
        matrix_keys.append({"id": tk["id"], "key_hex": tk["key_hex"], "msb_L": L[0] >> 7})

    alpha_cts, beta_cts, gamma_cts = [], [], []
    for tk in interop_keys:
        key = bytes.fromhex(tk["key_hex"])
        alpha_cts.append(alpha_crypto.encrypt(key, interop_nonce, interop_pt, interop_aad).hex())
        beta_cts.append(ref_encrypt(key, interop_nonce, interop_pt, interop_aad).hex())
        gamma_cts.append(gamma_crypto.encrypt(key, interop_nonce, interop_pt, interop_aad).hex())

    results = {
        "alpha_encrypt": {"alpha_decrypt": [], "beta_decrypt": [], "gamma_decrypt": []},
        "beta_encrypt": {"alpha_decrypt": [], "beta_decrypt": [], "gamma_decrypt": []},
        "gamma_encrypt": {"alpha_decrypt": [], "beta_decrypt": [], "gamma_decrypt": []},
    }

    for i, tk in enumerate(interop_keys):
        key = bytes.fromhex(tk["key_hex"])

        results["alpha_encrypt"]["alpha_decrypt"].append(
            try_decrypt(alpha_crypto.decrypt, key, interop_nonce, alpha_cts[i], interop_aad))
        results["alpha_encrypt"]["beta_decrypt"].append(
            try_decrypt(ref_decrypt, key, interop_nonce, alpha_cts[i], interop_aad))
        results["alpha_encrypt"]["gamma_decrypt"].append(
            try_decrypt(gamma_crypto.decrypt, key, interop_nonce, alpha_cts[i], interop_aad))

        results["beta_encrypt"]["alpha_decrypt"].append(
            try_decrypt(alpha_crypto.decrypt, key, interop_nonce, beta_cts[i], interop_aad))
        results["beta_encrypt"]["beta_decrypt"].append(
            try_decrypt(ref_decrypt, key, interop_nonce, beta_cts[i], interop_aad))
        results["beta_encrypt"]["gamma_decrypt"].append(
            try_decrypt(gamma_crypto.decrypt, key, interop_nonce, beta_cts[i], interop_aad))

        results["gamma_encrypt"]["alpha_decrypt"].append(
            try_decrypt(alpha_crypto.decrypt, key, interop_nonce, gamma_cts[i], interop_aad))
        results["gamma_encrypt"]["beta_decrypt"].append(
            try_decrypt(ref_decrypt, key, interop_nonce, gamma_cts[i], interop_aad))
        results["gamma_encrypt"]["gamma_decrypt"].append(
            try_decrypt(gamma_crypto.decrypt, key, interop_nonce, gamma_cts[i], interop_aad))

    matrix = {
        "description": "Cross-implementation interoperability matrix. Five test keys encrypted/decrypted across all three implementations.",
        "note": "Beta is a pre-compiled Go binary at /app/implementations/beta/xaes_tool",
        "test_keys": matrix_keys,
        "nonce_hex": "4142434445464748494a4b4c4d4e4f505152535455565758",
        "plaintext_ascii": "XAES-256-GCM",
        "results": results,
    }

    with open("/app/data/reports/interop_matrix.json", "w") as f:
        json.dump(matrix, f, indent=2)

    # ---- Generate 30 encrypted records (encrypted with Alpha) ----

    payload_templates = [
        "Patient assessment for case #A-{idx:03d}: vitals within normal range, BP 120/80, HR 72 bpm",
        "Laboratory results batch #{idx:03d}: hemoglobin 14.2 g/dL, WBC 6800/uL, platelets 250K/uL",
        "Prescription update #{idx:03d}: medication dosage adjusted per attending protocol Rev.3",
        "Discharge summary #{idx:03d}: patient clinically stable, follow-up scheduled in 14 days",
        "Radiology report #{idx:03d}: chest X-ray reveals no acute cardiopulmonary abnormality",
    ]
    type_names = ["medical", "laboratory", "pharmacy", "administrative", "imaging"]

    partner_a_lines = ["record_id,status,error_message"]
    partner_b_lines = ["record_id,status,error_message"]

    for i in range(NUM_RECORDS):
        record_id = f"record_{i:03d}"

        plaintext_data = {
            "id": record_id,
            "timestamp": f"2026-06-{(i % 28) + 1:02d}T{10 + (i % 12):02d}:00:00Z",
            "type": type_names[i % 5],
            "classification": "confidential",
            "payload": payload_templates[i % 5].format(idx=i),
        }
        plaintext_str = json.dumps(plaintext_data, indent=2)
        plaintext_bytes = plaintext_str.encode()

        with open(f"/app/data/plaintext/{record_id}.json", "w") as f:
            f.write(plaintext_str)

        key = hkdf_sha256(MASTER_KEY, SALT, record_id.encode())
        nonce = generate_nonce(nonce_seed, i)
        aad = f"audit-svc:{record_id}"

        ciphertext = alpha_crypto.encrypt(key, nonce, plaintext_bytes, aad.encode())

        enc_data = {
            "record_id": record_id,
            "nonce_hex": nonce.hex(),
            "aad": aad,
            "ciphertext_hex": ciphertext.hex(),
        }
        with open(f"/app/data/encrypted/{record_id}.enc", "w") as f:
            json.dump(enc_data, f, indent=2)

        L = AES_raw.new(key, AES_raw.MODE_ECB).encrypt(b"\x00" * 16)
        msb = L[0] >> 7

        if msb == 1:
            partner_a_lines.append(
                f"{record_id},fail,AEAD decryption error: authentication tag verification failed")
        else:
            partner_a_lines.append(f"{record_id},ok,")

        partner_b_lines.append(
            f"{record_id},fail,AEAD decryption error: authentication tag verification failed")

    with open("/app/data/reports/partner_A_beta_report.csv", "w") as f:
        f.write("\n".join(partner_a_lines) + "\n")

    with open("/app/data/reports/partner_B_gamma_report.csv", "w") as f:
        f.write("\n".join(partner_b_lines) + "\n")

    fail_a = sum(1 for line in partner_a_lines[1:] if ",fail," in line)
    print(f"Generated {NUM_RECORDS} records")
    print(f"Partner A (Beta impl): {fail_a}/{NUM_RECORDS} failures")
    print(f"Partner B (Gamma impl): {NUM_RECORDS}/{NUM_RECORDS} failures")
    print("Interop matrix written to /app/data/reports/interop_matrix.json")


if __name__ == "__main__":
    main()
