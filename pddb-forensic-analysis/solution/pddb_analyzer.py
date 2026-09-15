#!/usr/bin/env python3
"""
PDDB Page Table Security Audit -- reference solution.

Discovers cryptographic bases via brute-force key derivation, reconstructs
page table mappings, and performs a comprehensive security assessment
covering ECB mode vulnerabilities, CRC-32 integrity analysis, nonce
collision risk, and FSCB plausible-deniability leakage.

"""
import json
import hashlib
import hmac
import struct
import binascii
import math
import os
from collections import defaultdict

from Crypto.Cipher import AES

IMAGE_PATH = "/app/pddb_image.bin"
CONFIG_PATH = "/app/device_config.json"
PASSWORDS_PATH = "/app/passwords.txt"
NAMES_PATH = "/app/basis_names.txt"
FSCB_PATH = "/app/fscb.json"
FSCB_PREV_PATH = "/app/fscb_previous.json"
RESULTS_DIR = "/app/results"


def derive_key(device_salt, basis_name, password, iterations):
    """
    Three-stage PDDB key derivation following standard PRF conventions:
    1. Per-basis salt = HMAC-SHA256(key=device_salt, msg=basis_name)
       Device salt is the constant secret (HMAC key), basis name is variable.
    2. Stretched = PBKDF2-HMAC-SHA256(password, per_basis_salt, iter, 32)
    3. Final key = HMAC-SHA256(key=stretched, msg=domain_tag)
       Stretched material is key, domain tag is the purpose label.
    """
    per_basis_salt = hmac.new(
        device_salt, basis_name.encode("utf-8"), hashlib.sha256
    ).digest()
    stretched = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), per_basis_salt,
        iterations, dklen=32,
    )
    return hmac.new(
        stretched, b"pddb-page-table-key", hashlib.sha256
    ).digest()


def decrypt_entry(encrypted, key):
    return AES.new(key, AES.MODE_ECB).decrypt(encrypted)


def validate_entry(plaintext):
    data = plaintext[:12]
    stored_crc = struct.unpack("<I", plaintext[12:16])[0]
    return (binascii.crc32(data) & 0xFFFFFFFF) == stored_crc


def parse_entry(plaintext):
    vaddr = int.from_bytes(plaintext[:7], "little")
    flags = plaintext[7]
    nonce = struct.unpack("<I", plaintext[8:12])[0]
    return vaddr, flags, nonce


def main():
    # Load configuration
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    device_salt = bytes.fromhex(config["device_salt_hex"])
    iterations = config["pbkdf2_iterations"]
    num_entries = config["num_pt_entries"]

    with open(PASSWORDS_PATH) as f:
        passwords = [l.strip() for l in f if l.strip()]
    with open(NAMES_PATH) as f:
        basis_names = [l.strip() for l in f if l.strip()]
    with open(FSCB_PATH) as f:
        fscb_data = json.load(f)
    with open(FSCB_PREV_PATH) as f:
        fscb_prev_data = json.load(f)

    # Parse image header and read encrypted entries
    with open(IMAGE_PATH, "rb") as f:
        header = f.read(64)
        assert header[0:8] == b"PDDB_PT\x00", f"Bad magic: {header[0:8]}"
        n_entries = struct.unpack("<I", header[12:16])[0]
        pt_offset = struct.unpack("<I", header[16:20])[0]
        f.seek(pt_offset)
        encrypted_entries = [f.read(16) for _ in range(n_entries)]

    print(f"Loaded {n_entries} entries")
    print(f"Trying {len(basis_names)} names x {len(passwords)} passwords "
          f"= {len(basis_names) * len(passwords)} combinations")

    # ── Brute-force basis discovery ─────────────────────────────────────────
    discovered = {}
    total = len(basis_names) * len(passwords)
    attempt = 0

    for bname in basis_names:
        for pwd in passwords:
            attempt += 1
            if attempt % 100 == 0:
                print(f"  Progress: {attempt}/{total} "
                      f"({100*attempt/total:.1f}%)", flush=True)

            key = derive_key(device_salt, bname, pwd, iterations)

            valid = []
            for i in range(n_entries):
                dec = decrypt_entry(encrypted_entries[i], key)
                if validate_entry(dec):
                    vaddr, flags, nonce = parse_entry(dec)
                    valid.append({
                        "physical_page": i,
                        "virtual_address": vaddr,
                        "flags": flags,
                        "nonce": nonce,
                    })

            if len(valid) >= 5:
                discovered[bname] = {
                    "password": pwd,
                    "key_hex": key.hex(),
                    "num_entries": len(valid),
                    "entries": valid,
                }
                print(f"  FOUND basis '{bname}': {len(valid)} entries")
                break

    print(f"\nDiscovered {len(discovered)} bases")

    os.makedirs(RESULTS_DIR, exist_ok=True)

    # ── bases.json ──────────────────────────────────────────────────────────
    bases_out = {
        n: {
            "password": d["password"],
            "key_hex": d["key_hex"],
            "num_entries": d["num_entries"],
        }
        for n, d in discovered.items()
    }
    with open(f"{RESULTS_DIR}/bases.json", "w") as f:
        json.dump(bases_out, f, indent=2)

    # ── page_map.json ───────────────────────────────────────────────────────
    page_map = {n: d["entries"] for n, d in discovered.items()}
    with open(f"{RESULTS_DIR}/page_map.json", "w") as f:
        json.dump(page_map, f, indent=2)

    # ── Security Audit ──────────────────────────────────────────────────────

    # 1. ECB vulnerability: scan for identical ciphertext blocks
    ct_to_positions = defaultdict(list)
    for idx, enc in enumerate(encrypted_entries):
        ct_to_positions[enc.hex()].append(idx)

    dup_pairs = []
    for ct_hex, positions in ct_to_positions.items():
        if len(positions) >= 2:
            ct_bytes = bytes.fromhex(ct_hex)
            basis_attr = None
            for bname, d in discovered.items():
                key = bytes.fromhex(d["key_hex"])
                dec = decrypt_entry(ct_bytes, key)
                if validate_entry(dec):
                    basis_attr = bname
                    break
            for i in range(len(positions)):
                for j in range(i + 1, len(positions)):
                    dup_pairs.append({
                        "page_a": positions[i],
                        "page_b": positions[j],
                        "basis": basis_attr or "unknown",
                        "ciphertext_hex": ct_hex,
                    })

    # 2. CRC-32 false positive analysis
    # CRC-32 = 32 bits. Random decryption: P(CRC match) = 1/2^32
    per_entry_fp = 1.0 / (2**32)
    per_cred_fp = num_entries * per_entry_fp

    # 3. Nonce analysis: birthday-problem probabilities
    per_basis_prob = {}
    all_nonces = {}
    for bname, d in discovered.items():
        n = d["num_entries"]
        per_basis_prob[bname] = 1.0 - math.exp(
            -n * (n - 1) / (2.0 * (2**32))
        )
        all_nonces[bname] = [e["nonce"] for e in d["entries"]]

    cross_basis = {}
    bnames = list(discovered.keys())
    for i in range(len(bnames)):
        for j in range(i + 1, len(bnames)):
            n1 = discovered[bnames[i]]["num_entries"]
            n2 = discovered[bnames[j]]["num_entries"]
            cross_basis[f"{bnames[i]}_vs_{bnames[j]}"] = (
                1.0 - math.exp(-n1 * n2 / (2**32))
            )

    actual_collisions = []
    for bname, nonces in all_nonces.items():
        seen = set()
        for nv in nonces:
            if nv in seen:
                actual_collisions.append({"basis": bname, "nonce": nv})
            seen.add(nv)

    # 4. FSCB deniability metrics
    total_valid = sum(d["num_entries"] for d in discovered.values())
    unknown = num_entries - total_valid
    confirmed_free = len(fscb_data["free_pages"])
    max_hidden = unknown - confirmed_free
    den_ratio = confirmed_free / unknown if unknown > 0 else 0.0

    # 5. FSCB differential: temporal leakage analysis
    fscb_current = set(fscb_data["free_pages"])
    fscb_prev = set(fscb_prev_data["free_pages"])
    transitioned = fscb_prev - fscb_current

    known_pages = set()
    for d in discovered.values():
        known_pages.update(e["physical_page"] for e in d["entries"])

    attributable = len(transitioned & known_pages)
    unattributable = len(transitioned - known_pages)

    audit = {
        "ecb_vulnerability": {
            "duplicate_pairs": dup_pairs,
            "total_duplicate_pairs": len(dup_pairs),
            "vulnerability_present": len(dup_pairs) > 0,
        },
        "integrity_analysis": {
            "per_entry_false_positive_rate": per_entry_fp,
            "expected_false_positives_per_credential": per_cred_fp,
        },
        "nonce_analysis": {
            "per_basis_collision_probability": per_basis_prob,
            "cross_basis_collision_probability": cross_basis,
            "actual_nonce_collisions": actual_collisions,
        },
        "fscb_deniability": {
            "unknown_pages": unknown,
            "confirmed_free": confirmed_free,
            "max_potentially_hidden": max_hidden,
            "deniability_ratio": den_ratio,
        },
        "fscb_differential": {
            "transitioned_from_free": len(transitioned),
            "attributable_to_known_bases": attributable,
            "unattributable_transitions": unattributable,
            "leaked_hidden_activity": unattributable > 0,
        },
    }
    with open(f"{RESULTS_DIR}/security_audit.json", "w") as f:
        json.dump(audit, f, indent=2)

    print(f"\nResults written to {RESULTS_DIR}/")
    print(f"  Bases: {list(bases_out.keys())}")
    print(f"  ECB duplicate pairs: {len(dup_pairs)}")
    print(f"  Nonce collisions found: {len(actual_collisions)}")
    print(f"  FSCB transitions: {len(transitioned)} "
          f"(attributable: {attributable}, unattributable: {unattributable})")


if __name__ == "__main__":
    main()
