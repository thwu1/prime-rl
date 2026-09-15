#!/usr/bin/env python3
"""
Solution: TLS 1.3 session decryption.
Implements the TLS 1.3 key schedule (RFC 8446 Section 7.1) from scratch,
using only cryptography library for X25519 ECDH and AES-128-GCM primitives.

"""
import hashlib
import hmac as hmac_mod
import json
import os
import struct

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# ===== HKDF implementation (RFC 5869) =====

def hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    """HKDF-Extract: PRK = HMAC-Hash(salt, IKM)."""
    return hmac_mod.new(salt, ikm, hashlib.sha256).digest()


def hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    """HKDF-Expand: OKM = T(1) || T(2) || ... where T(i) = HMAC(PRK, T(i-1) || info || i)."""
    n = (length + 31) // 32
    okm = b""
    t = b""
    for i in range(1, n + 1):
        t = hmac_mod.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


# ===== TLS 1.3 key schedule functions (RFC 8446 Section 7.1) =====

def hkdf_expand_label(secret: bytes, label: str, context: bytes, length: int) -> bytes:
    """
    HKDF-Expand-Label(Secret, Label, Context, Length) =
        HKDF-Expand(Secret, HkdfLabel, Length)

    HkdfLabel = uint16(Length) || uint8(len("tls13 " + Label)) || "tls13 " + Label
                || uint8(len(Context)) || Context
    """
    tls_label = b"tls13 " + label.encode("ascii")
    hkdf_label = (
        struct.pack(">H", length)
        + struct.pack("B", len(tls_label))
        + tls_label
        + struct.pack("B", len(context))
        + context
    )
    return hkdf_expand(secret, hkdf_label, length)


def derive_secret(secret: bytes, label: str, messages: bytes) -> bytes:
    """
    Derive-Secret(Secret, Label, Messages) =
        HKDF-Expand-Label(Secret, Label, Transcript-Hash(Messages), Hash.length)
    """
    transcript_hash = hashlib.sha256(messages).digest()
    return hkdf_expand_label(secret, label, transcript_hash, 32)


def make_nonce(iv: bytes, seq_num: int) -> bytes:
    """Per-record nonce = IV XOR left-padded 64-bit sequence number."""
    seq_bytes = seq_num.to_bytes(12, "big")
    return bytes(a ^ b for a, b in zip(iv, seq_bytes))


# ===== TLS handshake parsing =====

def parse_server_hello_pubkey(server_hello: bytes) -> bytes:
    """Extract the server's X25519 public key from the ServerHello key_share extension."""
    offset = 4  # skip HandshakeType(1) + length(3)
    offset += 2  # legacy_version
    offset += 32  # random
    session_id_len = server_hello[offset]
    offset += 1 + session_id_len  # session_id
    offset += 2  # cipher_suite
    offset += 1  # compression_method

    # Extensions
    ext_total_len = struct.unpack(">H", server_hello[offset:offset + 2])[0]
    offset += 2
    ext_end = offset + ext_total_len

    while offset < ext_end:
        ext_type = struct.unpack(">H", server_hello[offset:offset + 2])[0]
        ext_len = struct.unpack(">H", server_hello[offset + 2:offset + 4])[0]

        if ext_type == 0x0033:  # key_share
            # ServerHello key_share: named_group(2) + key_exchange_length(2) + key_exchange
            ke_len = struct.unpack(">H", server_hello[offset + 6:offset + 8])[0]
            return server_hello[offset + 8:offset + 8 + ke_len]

        offset += 4 + ext_len

    raise ValueError("key_share extension (0x0033) not found in ServerHello")


def main():
    # Load session data
    with open("/app/session_data.json") as f:
        data = json.load(f)

    client_priv_bytes = bytes.fromhex(data["client_private_key_hex"])
    client_hello = bytes.fromhex(data["client_hello_hex"])
    server_hello = bytes.fromhex(data["server_hello_hex"])

    # Step 1: Extract server's X25519 public key from ServerHello
    server_pub_bytes = parse_server_hello_pubkey(server_hello)
    print(f"Server public key: {server_pub_bytes.hex()}")

    # Step 2: Compute ECDH shared secret
    client_private = X25519PrivateKey.from_private_bytes(client_priv_bytes)
    server_public = X25519PublicKey.from_public_bytes(server_pub_bytes)
    shared_secret = client_private.exchange(server_public)
    print(f"Shared secret: {shared_secret.hex()}")

    # Step 3: TLS 1.3 Key Schedule
    zeros = b"\x00" * 32

    # Early Secret (no PSK)
    early_secret = hkdf_extract(salt=zeros, ikm=zeros)

    # Handshake Secret
    derived_1 = derive_secret(early_secret, "derived", b"")
    handshake_secret = hkdf_extract(salt=derived_1, ikm=shared_secret)

    # Handshake traffic secrets (transcript = ClientHello || ServerHello)
    transcript_ch_sh = client_hello + server_hello
    c_hs_traffic = derive_secret(handshake_secret, "c hs traffic", transcript_ch_sh)
    s_hs_traffic = derive_secret(handshake_secret, "s hs traffic", transcript_ch_sh)

    # Handshake traffic keys
    c_hs_key = hkdf_expand_label(c_hs_traffic, "key", b"", 16)
    c_hs_iv = hkdf_expand_label(c_hs_traffic, "iv", b"", 12)
    s_hs_key = hkdf_expand_label(s_hs_traffic, "key", b"", 16)
    s_hs_iv = hkdf_expand_label(s_hs_traffic, "iv", b"", 12)

    print(f"Server handshake key: {s_hs_key.hex()}")

    # Step 4: Decrypt server handshake
    enc_hs = data["encrypted_handshake"]
    ct_hs = bytes.fromhex(enc_hs["ciphertext"])
    aad_hs = bytes.fromhex(enc_hs["additional_data"])
    nonce_hs = make_nonce(s_hs_iv, enc_hs["sequence_number"])

    aesgcm_hs = AESGCM(s_hs_key)
    inner_hs = aesgcm_hs.decrypt(nonce_hs, ct_hs, aad_hs)
    hs_plaintext = inner_hs[:-1]  # strip trailing content type byte (0x16)
    print(f"Decrypted handshake length: {len(hs_plaintext)} bytes")

    # Step 5: Derive application keys
    # Transcript for application keys includes the decrypted handshake
    transcript_full = client_hello + server_hello + hs_plaintext
    derived_2 = derive_secret(handshake_secret, "derived", b"")
    master_secret = hkdf_extract(salt=derived_2, ikm=zeros)

    c_ap_traffic = derive_secret(master_secret, "c ap traffic", transcript_full)
    s_ap_traffic = derive_secret(master_secret, "s ap traffic", transcript_full)

    c_ap_key = hkdf_expand_label(c_ap_traffic, "key", b"", 16)
    c_ap_iv = hkdf_expand_label(c_ap_traffic, "iv", b"", 12)
    s_ap_key = hkdf_expand_label(s_ap_traffic, "key", b"", 16)
    s_ap_iv = hkdf_expand_label(s_ap_traffic, "iv", b"", 12)

    print(f"Server application key: {s_ap_key.hex()}")

    # Step 6: Decrypt application data records
    aesgcm_app = AESGCM(s_ap_key)
    response = b""
    for i, rec in enumerate(data["encrypted_application_records"]):
        ct = bytes.fromhex(rec["ciphertext"])
        aad = bytes.fromhex(rec["additional_data"])
        seq = rec["sequence_number"]
        nonce = make_nonce(s_ap_iv, seq)
        inner = aesgcm_app.decrypt(nonce, ct, aad)
        plaintext = inner[:-1]  # strip content type byte
        response += plaintext
        print(f"  Record {i}: {len(plaintext)} bytes decrypted")

    response_text = response.decode("utf-8")
    print(f"\nDecrypted response ({len(response_text)} chars):")
    print(response_text[:200] + "...")

    # Step 7: Write output files
    os.makedirs("/app/output", exist_ok=True)

    with open("/app/output/shared_secret.hex", "w") as f:
        f.write(shared_secret.hex())

    with open("/app/output/handshake_keys.json", "w") as f:
        json.dump({
            "client_handshake_key": c_hs_key.hex(),
            "client_handshake_iv": c_hs_iv.hex(),
            "server_handshake_key": s_hs_key.hex(),
            "server_handshake_iv": s_hs_iv.hex(),
        }, f, indent=2)

    with open("/app/output/decrypted_handshake.hex", "w") as f:
        f.write(hs_plaintext.hex())

    with open("/app/output/application_keys.json", "w") as f:
        json.dump({
            "client_application_key": c_ap_key.hex(),
            "client_application_iv": c_ap_iv.hex(),
            "server_application_key": s_ap_key.hex(),
            "server_application_iv": s_ap_iv.hex(),
        }, f, indent=2)

    with open("/app/output/decrypted_response.txt", "w") as f:
        f.write(response_text)

    print("\nAll output files written to /app/output/")


if __name__ == "__main__":
    main()
