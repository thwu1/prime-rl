#!/usr/bin/env python3
"""
QUIC Packet Protection Pipeline for v1 (RFC 9001) and v2 (RFC 9369).

Implements:
- HKDF-Extract + HKDF-Expand-Label (TLS 1.3) for key derivation
- AEAD_AES_128_GCM packet protection with AES-ECB header protection
- Retry packet integrity tag computation
- ChaCha20-Poly1305 packet protection with ChaCha20 header protection

"""

import json
import hashlib
import hmac
import struct
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def hkdf_extract(salt, ikm):
    """HKDF-Extract (RFC 5869) using HMAC-SHA256."""
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def hkdf_expand(prk, info, length):
    """HKDF-Expand (RFC 5869) using HMAC-SHA256."""
    hash_len = 32
    n = (length + hash_len - 1) // hash_len
    okm = b""
    t = b""
    for i in range(1, n + 1):
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


def hkdf_expand_label(secret, label, context, length):
    """TLS 1.3 HKDF-Expand-Label (RFC 8446 Section 7.1).

    Constructs HkdfLabel:
        struct {
            uint16 length;
            opaque label<7..255> = "tls13 " + Label;
            opaque context<0..255> = Context;
        } HkdfLabel;
    """
    full_label = b"tls13 " + label.encode("ascii")
    info = (
        struct.pack(">H", length)
        + bytes([len(full_label)])
        + full_label
        + bytes([len(context)])
        + context
    )
    return hkdf_expand(secret, info, length)


def aes_ecb_encrypt(key, plaintext):
    """Single-block AES-ECB encryption."""
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(plaintext) + enc.finalize()


def protect_initial_packet(header, payload, key, iv, hp_key, packet_number):
    """Protect a QUIC Initial packet (AEAD_AES_128_GCM + AES-ECB header protection)."""
    # 1. Construct AEAD nonce: IV XOR zero-padded packet number
    pn_padded = packet_number.to_bytes(len(iv), "big")
    nonce = bytes(a ^ b for a, b in zip(iv, pn_padded))

    # 2. AEAD encrypt (header is the associated data)
    aead = AESGCM(key)
    ciphertext = aead.encrypt(nonce, payload, header)

    # 3. Determine packet number length from header first byte
    pn_length = (header[0] & 0x03) + 1

    # 4. Sample 16 bytes for header protection
    sample_offset = 4 - pn_length
    sample = ciphertext[sample_offset : sample_offset + 16]

    # 5. Compute header protection mask via AES-ECB
    mask = aes_ecb_encrypt(hp_key, sample)

    # 6. Apply mask to header
    packet = bytearray(header) + bytearray(ciphertext)

    # Long header: mask lower 4 bits of first byte
    packet[0] ^= mask[0] & 0x0F

    # Mask the packet number bytes
    pn_offset = len(header) - pn_length
    for i in range(pn_length):
        packet[pn_offset + i] ^= mask[1 + i]

    return bytes(packet)


def compute_retry_integrity_tag(key, nonce, odcid, retry_packet_no_tag):
    """Compute Retry packet integrity tag using AEAD_AES_128_GCM."""
    pseudo_packet = bytes([len(odcid)]) + odcid + retry_packet_no_tag
    aead = AESGCM(key)
    tag = aead.encrypt(nonce, b"", pseudo_packet)
    return tag


def protect_chacha20_packet(header, payload, key, iv, hp_key, packet_number):
    """Protect a QUIC short header packet using ChaCha20-Poly1305 + ChaCha20 HP."""
    # 1. Construct AEAD nonce
    pn_padded = packet_number.to_bytes(len(iv), "big")
    nonce = bytes(a ^ b for a, b in zip(iv, pn_padded))

    # 2. AEAD encrypt with ChaCha20-Poly1305
    aead = ChaCha20Poly1305(key)
    ciphertext = aead.encrypt(nonce, payload, header)

    # 3. Determine packet number length
    pn_length = (header[0] & 0x03) + 1

    # 4. Sample 16 bytes for header protection
    sample_offset = 4 - pn_length
    sample = ciphertext[sample_offset : sample_offset + 16]

    # 5. ChaCha20 header protection
    # sample[0:4] = counter (little-endian), sample[4:16] = nonce
    chacha_nonce = sample[0:16]
    cipher = Cipher(algorithms.ChaCha20(hp_key, chacha_nonce), mode=None)
    enc = cipher.encryptor()
    mask = enc.update(b"\x00" * 5)

    # 6. Apply mask to header (short header: mask lower 5 bits of first byte)
    packet = bytearray(header) + bytearray(ciphertext)
    packet[0] ^= mask[0] & 0x1F

    pn_offset = len(header) - pn_length
    for i in range(pn_length):
        packet[pn_offset + i] ^= mask[1 + i]

    return bytes(packet)


def main():
    # Load input vectors from /data/ (persisted from Docker build, not /app/ which is workdir)
    with open("/data/vectors.json") as f:
        vectors = json.load(f)

    dcid = bytes.fromhex(vectors["dcid_hex"])

    # Version-specific constants
    VERSION_CONFIG = {
        "v1": {
            "salt": bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a"),
            "key_label": "quic key",
            "iv_label": "quic iv",
            "hp_label": "quic hp",
            "retry_key": bytes.fromhex("be0c690b9f66575a1d766b54e368c84e"),
            "retry_nonce": bytes.fromhex("461599d35d632bf2239825bb"),
        },
        "v2": {
            "salt": bytes.fromhex("0dede3def700a6db819381be6e269dcbf9bd2ed9"),
            "key_label": "quicv2 key",
            "iv_label": "quicv2 iv",
            "hp_label": "quicv2 hp",
            "retry_key": bytes.fromhex("8fb4b01b56ac48e260fbcbcead7ccc92"),
            "retry_nonce": bytes.fromhex("d86969bc2d7c6d9990efb04a"),
        },
    }

    results = {}

    for version, cfg in VERSION_CONFIG.items():
        # --- Key Derivation ---
        initial_secret = hkdf_extract(cfg["salt"], dcid)

        client_initial_secret = hkdf_expand_label(initial_secret, "client in", b"", 32)
        server_initial_secret = hkdf_expand_label(initial_secret, "server in", b"", 32)

        client_key = hkdf_expand_label(client_initial_secret, cfg["key_label"], b"", 16)
        client_iv = hkdf_expand_label(client_initial_secret, cfg["iv_label"], b"", 12)
        client_hp = hkdf_expand_label(client_initial_secret, cfg["hp_label"], b"", 16)

        server_key = hkdf_expand_label(server_initial_secret, cfg["key_label"], b"", 16)
        server_iv = hkdf_expand_label(server_initial_secret, cfg["iv_label"], b"", 12)
        server_hp = hkdf_expand_label(server_initial_secret, cfg["hp_label"], b"", 16)

        vr = {
            "initial_secret": initial_secret.hex(),
            "client_initial_secret": client_initial_secret.hex(),
            "client_key": client_key.hex(),
            "client_iv": client_iv.hex(),
            "client_hp": client_hp.hex(),
            "server_initial_secret": server_initial_secret.hex(),
            "server_key": server_key.hex(),
            "server_iv": server_iv.hex(),
            "server_hp": server_hp.hex(),
        }

        # --- Client Initial Packet Protection ---
        ci = vectors["client_initial"]
        c_header = bytes.fromhex(ci[f"{version}_unprotected_header_hex"])
        crypto_frame = bytes.fromhex(vectors["crypto_frame_hex"])
        # Pad payload to total_payload_length with zero bytes (PADDING frames)
        c_payload = crypto_frame + b"\x00" * (ci["total_payload_length"] - len(crypto_frame))

        c_protected = protect_initial_packet(
            c_header, c_payload, client_key, client_iv, client_hp, ci["packet_number"]
        )
        vr["client_initial_protected_packet"] = c_protected.hex()

        # --- Server Initial Packet Protection ---
        si = vectors["server_initial"]
        s_header = bytes.fromhex(si[f"{version}_unprotected_header_hex"])
        s_payload = bytes.fromhex(si["payload_hex"])

        s_protected = protect_initial_packet(
            s_header, s_payload, server_key, server_iv, server_hp, si["packet_number"]
        )
        vr["server_initial_protected_packet"] = s_protected.hex()

        # --- Retry Packet Integrity Tag ---
        retry = vectors["retry"]
        odcid = bytes.fromhex(retry["odcid_hex"])
        retry_no_tag = bytes.fromhex(retry[f"{version}_retry_without_tag_hex"])

        tag = compute_retry_integrity_tag(
            cfg["retry_key"], cfg["retry_nonce"], odcid, retry_no_tag
        )
        vr["retry_packet"] = (retry_no_tag + tag).hex()

        # --- ChaCha20-Poly1305 Short Header Packet ---
        cc = vectors["chacha20_short_header"]
        cc_secret = bytes.fromhex(cc["secret_hex"])

        # Derive ChaCha20 keys (32-byte key, 12-byte IV, 32-byte HP key)
        cc_key = hkdf_expand_label(cc_secret, cfg["key_label"], b"", 32)
        cc_iv = hkdf_expand_label(cc_secret, cfg["iv_label"], b"", 12)
        cc_hp_key = hkdf_expand_label(cc_secret, cfg["hp_label"], b"", 32)

        cc_header = bytes.fromhex(cc["unprotected_header_hex"])
        cc_plaintext = bytes.fromhex(cc["payload_plaintext_hex"])

        cc_protected = protect_chacha20_packet(
            cc_header, cc_plaintext, cc_key, cc_iv, cc_hp_key, cc["packet_number"]
        )
        vr["chacha20_protected_packet"] = cc_protected.hex()

        results[version] = vr

    # Write output
    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/output/results.json")


if __name__ == "__main__":
    main()
