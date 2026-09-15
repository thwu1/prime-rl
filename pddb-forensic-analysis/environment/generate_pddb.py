#!/usr/bin/env python3
"""
Generate synthetic PDDB page table image for security audit task.
Deterministic via fixed seed. Plants ECB duplicate ciphertext blocks
and generates both current and previous FSCB snapshots for differential
analysis.

"""
import hashlib
import hmac
import struct
import os
import json
import random
import binascii
from Crypto.Cipher import AES

SEED = 0xDEADBEEFCAFEBABE
DEVICE_SALT = bytes.fromhex(
    "a3b7c9d1e5f20a1b3c4d5e6f7a8b9c0d"
    "1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b"
)
NUM_PT_ENTRIES = 2000
PBKDF2_ITERATIONS = 10000

BASES = [
    (".System",    "precursor_boot_2024",  400),
    ("documents",  "my_d0cuments_key",     250),
    ("vault",      "pl4us1bly_d3n14bl3",   180),
    ("operations", "cl4ss1f1ed_alpha",     120),
]

# ECB duplicate map: basis_index -> {dup_entry_idx: source_entry_idx}
# Entry at dup_entry_idx will have identical plaintext to source_entry_idx,
# producing identical ciphertext under ECB mode (the vulnerability to detect).
ECB_DUP_MAP = {0: {50: 10, 200: 100}}


def derive_key(device_salt, basis_name, password):
    per_basis_salt = hmac.new(
        device_salt, basis_name.encode("utf-8"), hashlib.sha256
    ).digest()
    stretched = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), per_basis_salt,
        PBKDF2_ITERATIONS, dklen=32,
    )
    return hmac.new(stretched, b"pddb-page-table-key", hashlib.sha256).digest()


def make_entry(vaddr, flags, nonce):
    vaddr_bytes = struct.pack("<Q", vaddr)[:7]
    flags_byte = struct.pack("B", flags)
    nonce_bytes = struct.pack("<I", nonce)
    data = vaddr_bytes + flags_byte + nonce_bytes  # 12 bytes
    crc = binascii.crc32(data) & 0xFFFFFFFF
    return data + struct.pack("<I", crc)


def encrypt_entry(entry, key):
    return AES.new(key, AES.MODE_ECB).encrypt(entry)


def generate(output_dir):
    rng = random.Random(SEED)
    entries = [None] * NUM_PT_ENTRIES
    basis_info = {}
    used_positions = set()

    for basis_idx, (basis_name, password, num_entries) in enumerate(BASES):
        key = derive_key(DEVICE_SALT, basis_name, password)
        basis_entries = []
        used_vaddrs = set()
        dup_map = ECB_DUP_MAP.get(basis_idx, {})
        entry_cache = {}  # entry_idx -> plaintext bytes

        for i in range(num_entries):
            # Assign unique physical page position
            while True:
                pos = rng.randint(0, NUM_PT_ENTRIES - 1)
                if pos not in used_positions:
                    break
            used_positions.add(pos)

            if i in dup_map:
                # Duplicate: reuse plaintext from source entry (ECB determinism)
                plaintext = entry_cache[dup_map[i]]
                vaddr = int.from_bytes(plaintext[:7], "little")
                flags = plaintext[7]
                nonce = struct.unpack("<I", plaintext[8:12])[0]
            else:
                # Generate unique entry
                if i == 0:
                    vaddr = 0x0000000000000FE0  # basis root page
                else:
                    while True:
                        dict_idx = rng.randint(0, 15)
                        page_off = rng.randint(1, 4095)
                        vaddr = 0xFE0000 + dict_idx * 0xFE0000 + page_off * 0xFE0
                        if vaddr not in used_vaddrs:
                            break
                used_vaddrs.add(vaddr)

                flags = 0x01  # valid
                if rng.random() < 0.3:
                    flags |= 0x02  # dirty
                if rng.random() < 0.1:
                    flags |= 0x04  # clean

                nonce = rng.randint(0, 0xFFFFFFFF)
                plaintext = make_entry(vaddr, flags, nonce)
                entry_cache[i] = plaintext

            encrypted = encrypt_entry(plaintext, key)
            entries[pos] = encrypted

            basis_entries.append({
                "phys_page": pos,
                "vaddr": vaddr,
                "flags": flags,
                "nonce": nonce,
            })

        basis_info[basis_name] = {
            "password": password,
            "key_hex": key.hex(),
            "num_entries": num_entries,
            "entries": basis_entries,
        }

    # Fill remaining positions with random noise
    for i in range(NUM_PT_ENTRIES):
        if entries[i] is None:
            entries[i] = bytes([rng.randint(0, 255) for _ in range(16)])

    # Current FSCB: cache ~50% of noise positions
    noise_positions = sorted(set(range(NUM_PT_ENTRIES)) - used_positions)
    fscb_count = len(noise_positions) // 2
    fscb_pages = sorted(rng.sample(noise_positions, fscb_count))

    # Previous FSCB: current + some now-allocated basis pages + unattributable noise
    prev_basis_pages = []
    for bn, pw, ne in BASES:
        bp = [e["phys_page"] for e in basis_info[bn]["entries"]]
        sc = max(2, len(bp) // 10)
        prev_basis_pages.extend(rng.sample(bp, sc))

    non_fscb_noise = sorted(set(noise_positions) - set(fscb_pages))
    unattrib_count = min(35, len(non_fscb_noise))
    unattrib_pages = rng.sample(non_fscb_noise, unattrib_count)

    fscb_prev_pages = sorted(
        set(fscb_pages) | set(prev_basis_pages) | set(unattrib_pages)
    )

    # === Write binary image ===
    pt_offset = 64
    header = bytearray(64)
    header[0:8] = b"PDDB_PT\x00"
    struct.pack_into("<I", header, 8, 1)                # version
    struct.pack_into("<I", header, 12, NUM_PT_ENTRIES)  # num_entries
    struct.pack_into("<I", header, 16, pt_offset)       # pt_offset
    struct.pack_into("<I", header, 20, pt_offset + NUM_PT_ENTRIES * 16)  # fscb_offset
    struct.pack_into("<I", header, 24, fscb_count)      # fscb_count
    struct.pack_into("<I", header, 28, NUM_PT_ENTRIES)  # total_pages

    with open(os.path.join(output_dir, "pddb_image.bin"), "wb") as f:
        f.write(header)
        for e in entries:
            f.write(e)
        for p in fscb_pages:
            f.write(struct.pack("<I", p))

    # === Write device config (deliberately ambiguous KDF description) ===
    config = {
        "device_salt_hex": DEVICE_SALT.hex(),
        "num_pt_entries": NUM_PT_ENTRIES,
        "pbkdf2_iterations": PBKDF2_ITERATIONS,
        "key_derivation": {
            "primitives": ["HMAC-SHA256", "PBKDF2-HMAC-SHA256"],
            "domain_tag": "pddb-page-table-key",
            "description": (
                "Three-stage key derivation: device salt and basis name "
                "produce a per-basis salt via HMAC-SHA256, which feeds "
                "PBKDF2-HMAC-SHA256 password stretching (iterations and "
                "dklen=32 as specified), yielding stretched material that "
                "undergoes HMAC-SHA256 domain separation with the domain "
                "tag to produce the final AES-256 key."
            ),
        },
        "entry_format": {
            "size": 16,
            "cipher": "AES-256-ECB",
            "plaintext_layout": (
                "vaddr:7B_LE flags:1B nonce:4B_LE integrity:4B_LE"
            ),
            "integrity_check": (
                "CRC-32 of bytes [0:12] stored little-endian at [12:16]"
            ),
            "flag_bits": "bit0=valid bit1=dirty bit2=clean",
        },
        "image_format": {
            "header_size": 64,
            "magic": "PDDB_PT\\0",
            "header_fields": (
                "version:u32le@8 num_entries:u32le@12 pt_offset:u32le@16 "
                "fscb_offset:u32le@20 fscb_count:u32le@24 total_pages:u32le@28"
            ),
            "layout": (
                "header || num_entries encrypted 16-byte blocks at pt_offset "
                "|| fscb_count u32le free-page indices at fscb_offset"
            ),
        },
        "notes": (
            "All strings UTF-8. Device salt used as raw bytes from hex. "
            "Physical page index = entry position in array (0-based). "
            "FSCB caches a subset of genuinely free pages; it is not exhaustive."
        ),
    }
    with open(os.path.join(output_dir, "device_config.json"), "w") as f:
        json.dump(config, f, indent=2)

    # === Write password candidates ===
    decoys = [
        "password123", "admin2024", "letmein99", "welcome_1", "qwerty2024",
        "changeme!", "trustno1x", "dragon_42", "master_key", "shadow_99",
        "sunshine1", "princess2", "football4", "batman_99", "access_now",
        "monkey_23", "1234567x0", "starwars_", "whatever4", "dragonbrn",
        "hunter2024", "buster_42", "charlie99", "thomas202", "george_42",
        "pepper_99", "daniel__x", "robert_42", "matthew_x", "joshua_99",
        "andrew_42", "james_x99", "john_99ab", "david_42x", "william_x",
        "secret_ba", "hidden_da", "encrypted", "secure_pw", "crypto_ky",
        "vault_opn", "deniable_", "covert_op", "stealth42", "phantom99",
        "r00tkit_x", "overflow_", "kern3l_42", "privesc99", "zeroday_1",
    ]
    reals = [p for _, p, _ in BASES]
    all_passwords = decoys + reals
    rng.shuffle(all_passwords)
    with open(os.path.join(output_dir, "passwords.txt"), "w") as f:
        for p in all_passwords:
            f.write(p + "\n")

    # === Write basis name candidates ===
    decoy_names = [
        "personal", "work", "finance", "medical", "legal",
        "photos", "messages", "contacts", "calendar", "notes",
        "projects", "research", "archive", "backup", "temp",
        "private", "shared", "public", "drafts", "inbox",
        "crypto", "keys", "tokens", "certs", "secrets",
    ]
    real_names = [n for n, _, _ in BASES]
    all_names = decoy_names + real_names
    rng.shuffle(all_names)
    with open(os.path.join(output_dir, "basis_names.txt"), "w") as f:
        for n in all_names:
            f.write(n + "\n")

    # === Write current FSCB ===
    with open(os.path.join(output_dir, "fscb.json"), "w") as f:
        json.dump({
            "free_pages": fscb_pages,
            "cache_policy": "approximately 50 percent of actual free space",
        }, f)

    # === Write previous FSCB snapshot ===
    with open(os.path.join(output_dir, "fscb_previous.json"), "w") as f:
        json.dump({
            "free_pages": fscb_prev_pages,
            "snapshot_note": (
                "FSCB state captured prior to most recent basis operations"
            ),
            "cache_policy": "approximately 50 percent of actual free space",
        }, f)

    total_valid = sum(n for _, _, n in BASES)
    print(
        f"Generated: {total_valid} valid entries, "
        f"{NUM_PT_ENTRIES - total_valid} noise, "
        f"{fscb_count} current FSCB, "
        f"{len(fscb_prev_pages)} previous FSCB"
    )


if __name__ == "__main__":
    out = "/generated"
    os.makedirs(out, exist_ok=True)
    generate(out)
