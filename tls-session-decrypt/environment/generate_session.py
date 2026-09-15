#!/usr/bin/env python3
"""
Generate a synthetic TLS 1.3 session for the decryption challenge.
Uses TLS_AES_128_GCM_SHA256 with X25519 key exchange.
All intermediate values follow the TLS 1.3 key schedule (RFC 8446 Section 7.1).
"""
import hashlib
import hmac as hmac_mod
import json
import os
import struct

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    """HKDF-Extract (RFC 5869 Section 2.2): PRK = HMAC-Hash(salt, IKM)."""
    return hmac_mod.new(salt, ikm, hashlib.sha256).digest()


def hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    """HKDF-Expand (RFC 5869 Section 2.3)."""
    hash_len = 32
    n = (length + hash_len - 1) // hash_len
    okm = b""
    t = b""
    for i in range(1, n + 1):
        t = hmac_mod.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


def hkdf_expand_label(secret: bytes, label: str, context: bytes, length: int) -> bytes:
    """TLS 1.3 HKDF-Expand-Label (RFC 8446 Section 7.1)."""
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
    """TLS 1.3 Derive-Secret (RFC 8446 Section 7.1)."""
    transcript_hash = hashlib.sha256(messages).digest()
    return hkdf_expand_label(secret, label, transcript_hash, 32)


def make_nonce(iv: bytes, seq_num: int) -> bytes:
    """Per-record nonce: IV XOR left-padded sequence number."""
    seq_bytes = seq_num.to_bytes(12, "big")
    return bytes(a ^ b for a, b in zip(iv, seq_bytes))


def build_extension(ext_type: int, data: bytes) -> bytes:
    """Build a TLS extension: type(2) + length(2) + data."""
    return struct.pack(">HH", ext_type, len(data)) + data


def main():
    # Deterministic private keys
    client_priv_bytes = bytes.fromhex(
        "b0b1b2b3b4b5b6b7b8b9babbbcbdbebfc0c1c2c3c4c5c6c7c8c9cacbcccdcecf"
    )
    server_priv_bytes = bytes.fromhex(
        "d0d1d2d3d4d5d6d7d8d9dadbdcdddedfe0e1e2e3e4e5e6e7e8e9eaebecedeeef"
    )

    client_private = X25519PrivateKey.from_private_bytes(client_priv_bytes)
    server_private = X25519PrivateKey.from_private_bytes(server_priv_bytes)

    client_pub = client_private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    server_pub = server_private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    # ECDH shared secret
    shared_secret = client_private.exchange(server_private.public_key())

    # Deterministic random values for ClientHello/ServerHello
    client_random = bytes.fromhex("aabbccdd" * 8)  # 32 bytes
    server_random = bytes.fromhex("11223344" * 8)  # 32 bytes

    # ===== Build ClientHello =====
    hostname = b"secret.test.io"
    # SNI extension (type 0x0000)
    sni_entry = b"\x00" + struct.pack(">H", len(hostname)) + hostname
    sni_list = struct.pack(">H", len(sni_entry)) + sni_entry
    sni_ext = build_extension(0x0000, sni_list)

    # Supported versions extension (type 0x002B) - client offers TLS 1.3
    sv_data = b"\x01\x03\x04"  # list length=1, version=0x0304
    sv_ext = build_extension(0x002B, sv_data)

    # Key share extension (type 0x0033) - client's X25519 public key
    ks_entry = struct.pack(">HH", 0x001D, len(client_pub)) + client_pub
    ks_data = struct.pack(">H", len(ks_entry)) + ks_entry
    ks_ext = build_extension(0x0033, ks_data)

    extensions = sni_ext + sv_ext + ks_ext
    ch_body = (
        b"\x03\x03"                              # legacy_version: TLS 1.2
        + client_random                           # random (32 bytes)
        + b"\x00"                                 # session_id length = 0
        + b"\x00\x02\x13\x01"                    # cipher_suites: 1 suite (TLS_AES_128_GCM_SHA256)
        + b"\x01\x00"                             # compression_methods: 1 method (null)
        + struct.pack(">H", len(extensions))      # extensions length
        + extensions
    )
    client_hello = b"\x01" + struct.pack(">I", len(ch_body))[1:] + ch_body

    # ===== Build ServerHello =====
    # Supported versions extension - server selects TLS 1.3
    sv_ext_srv = build_extension(0x002B, b"\x03\x04")

    # Key share extension - server's X25519 public key
    ks_srv_data = struct.pack(">HH", 0x001D, len(server_pub)) + server_pub
    ks_ext_srv = build_extension(0x0033, ks_srv_data)

    sh_extensions = sv_ext_srv + ks_ext_srv
    sh_body = (
        b"\x03\x03"                              # legacy_version: TLS 1.2
        + server_random                           # random (32 bytes)
        + b"\x00"                                 # session_id length = 0
        + b"\x13\x01"                             # cipher_suite: TLS_AES_128_GCM_SHA256
        + b"\x00"                                 # compression_method: null
        + struct.pack(">H", len(sh_extensions))   # extensions length
        + sh_extensions
    )
    server_hello = b"\x02" + struct.pack(">I", len(sh_body))[1:] + sh_body

    # ===== TLS 1.3 Key Schedule =====
    zeros_32 = b"\x00" * 32

    # Step 1: Early Secret (no PSK, so IKM = zeros)
    early_secret = hkdf_extract(salt=zeros_32, ikm=zeros_32)

    # Step 2: Handshake Secret
    derived_1 = derive_secret(early_secret, "derived", b"")
    handshake_secret = hkdf_extract(salt=derived_1, ikm=shared_secret)

    # Step 3: Handshake traffic secrets (transcript = CH || SH)
    transcript_ch_sh = client_hello + server_hello
    c_hs_traffic = derive_secret(handshake_secret, "c hs traffic", transcript_ch_sh)
    s_hs_traffic = derive_secret(handshake_secret, "s hs traffic", transcript_ch_sh)

    # Step 4: Handshake traffic keys
    c_hs_key = hkdf_expand_label(c_hs_traffic, "key", b"", 16)
    c_hs_iv = hkdf_expand_label(c_hs_traffic, "iv", b"", 12)
    s_hs_key = hkdf_expand_label(s_hs_traffic, "key", b"", 16)
    s_hs_iv = hkdf_expand_label(s_hs_traffic, "iv", b"", 12)

    # ===== Server Handshake Plaintext =====
    # EncryptedExtensions (type 0x08, no extensions)
    ee = b"\x08\x00\x00\x02\x00\x00"

    # Certificate (type 0x0b, simplified)
    cert_data = b"CN=secret.test.io;O=TestOrg;SN=42"
    cert_entry = struct.pack(">I", len(cert_data))[1:] + cert_data + b"\x00\x00"
    cert_list = struct.pack(">I", len(cert_entry))[1:] + cert_entry
    cert_body = b"\x00" + cert_list  # request_context(0) + cert_list
    certificate = b"\x0b" + struct.pack(">I", len(cert_body))[1:] + cert_body

    # CertificateVerify (type 0x0f)
    sig = hashlib.sha256(b"cert_verify_sig").digest()
    cv_body = b"\x08\x04" + struct.pack(">H", len(sig)) + sig
    cert_verify = b"\x0f" + struct.pack(">I", len(cv_body))[1:] + cv_body

    # Finished (type 0x14)
    fin_data = hashlib.sha256(b"server_finished").digest()
    finished = b"\x14" + struct.pack(">I", len(fin_data))[1:] + fin_data

    server_hs_plaintext = ee + certificate + cert_verify + finished

    # Encrypt server handshake (inner = plaintext + content_type_byte)
    inner_hs = server_hs_plaintext + b"\x16"  # ContentType: Handshake (0x16)
    aad_hs = b"\x17\x03\x03" + struct.pack(">H", len(inner_hs) + 16)  # +16 for GCM tag
    aesgcm_hs = AESGCM(s_hs_key)
    nonce_hs = make_nonce(s_hs_iv, 0)
    encrypted_hs = aesgcm_hs.encrypt(nonce_hs, inner_hs, aad_hs)

    # ===== Application Keys =====
    # Transcript for app keys: CH || SH || decrypted_server_handshake
    transcript_full = client_hello + server_hello + server_hs_plaintext
    derived_2 = derive_secret(handshake_secret, "derived", b"")
    master_secret = hkdf_extract(salt=derived_2, ikm=zeros_32)

    c_ap_traffic = derive_secret(master_secret, "c ap traffic", transcript_full)
    s_ap_traffic = derive_secret(master_secret, "s ap traffic", transcript_full)

    c_ap_key = hkdf_expand_label(c_ap_traffic, "key", b"", 16)
    c_ap_iv = hkdf_expand_label(c_ap_traffic, "iv", b"", 12)
    s_ap_key = hkdf_expand_label(s_ap_traffic, "key", b"", 16)
    s_ap_iv = hkdf_expand_label(s_ap_traffic, "iv", b"", 12)

    # ===== Encrypt Application Data Records =====
    app_plaintexts = [
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n",
        b"<html><head><title>Classified</title></head><body>",
        b"<h1>Operation Nightingale</h1>",
        b"<p>Authorization Code: FOXTROT-LIMA-2847-SIERRA</p>",
        b"<p>Rendezvous coordinates: 48.8566N, 2.3522E</p>",
        b"</body></html>",
    ]

    encrypted_app = []
    aesgcm_app = AESGCM(s_ap_key)
    for i, pt in enumerate(app_plaintexts):
        inner = pt + b"\x17"  # ContentType: ApplicationData (0x17)
        rec_len = len(inner) + 16  # +16 for GCM tag
        aad = b"\x17\x03\x03" + struct.pack(">H", rec_len)
        nonce = make_nonce(s_ap_iv, i)
        ct = aesgcm_app.encrypt(nonce, inner, aad)
        encrypted_app.append({
            "ciphertext": ct.hex(),
            "additional_data": aad.hex(),
            "sequence_number": i,
        })

    # ===== Write session_data.json =====
    session_data = {
        "description": (
            "Captured TLS 1.3 session using TLS_AES_128_GCM_SHA256 with X25519 "
            "key exchange. The client's X25519 private key is known. Your task is "
            "to implement the TLS 1.3 key schedule from scratch, derive all traffic "
            "keys, and decrypt the handshake and application data records."
        ),
        "cipher_suite": "TLS_AES_128_GCM_SHA256",
        "key_exchange": "X25519",
        "client_private_key_hex": client_priv_bytes.hex(),
        "client_hello_hex": client_hello.hex(),
        "server_hello_hex": server_hello.hex(),
        "encrypted_handshake": {
            "ciphertext": encrypted_hs.hex(),
            "additional_data": aad_hs.hex(),
            "sequence_number": 0,
        },
        "encrypted_application_records": encrypted_app,
        "notes": {
            "key_schedule": (
                "TLS 1.3 key schedule per RFC 8446 Section 7.1. No PSK is used, "
                "so PSK and the initial salt are both zeros(32). "
                "early_secret = HKDF-Extract(salt=zeros, ikm=zeros). "
                "Then: derived = Derive-Secret(early_secret, 'derived', ''), "
                "handshake_secret = HKDF-Extract(salt=derived, ikm=shared_secret). "
                "Handshake traffic secrets use transcript = ClientHello || ServerHello. "
                "For master_secret: derived2 = Derive-Secret(handshake_secret, 'derived', ''), "
                "master_secret = HKDF-Extract(salt=derived2, ikm=zeros). "
                "Application traffic secrets use transcript = "
                "ClientHello || ServerHello || decrypted_server_handshake_plaintext."
            ),
            "derive_secret": (
                "Derive-Secret(Secret, Label, Messages) = "
                "HKDF-Expand-Label(Secret, Label, Transcript-Hash(Messages), Hash.length). "
                "Transcript-Hash is SHA-256 of the concatenated messages."
            ),
            "hkdf_expand_label": (
                "HKDF-Expand-Label(Secret, Label, Context, Length) = "
                "HKDF-Expand(Secret, HkdfLabel, Length) where HkdfLabel is: "
                "uint16(Length) || uint8(len('tls13 ' + Label)) || 'tls13 ' + Label "
                "|| uint8(len(Context)) || Context. All multi-byte integers are big-endian."
            ),
            "traffic_keys": (
                "From a traffic secret, derive: "
                "key = HKDF-Expand-Label(secret, 'key', '', key_length=16), "
                "iv = HKDF-Expand-Label(secret, 'iv', '', iv_length=12)."
            ),
            "record_format": (
                "TLS 1.3 encrypted records: the inner plaintext is "
                "content || content_type_byte (1 byte). After decryption, strip "
                "the trailing byte. Content type 0x16 = Handshake, 0x17 = ApplicationData."
            ),
            "nonce": (
                "Per-record nonce = IV XOR pad_left(sequence_number, 12 bytes). "
                "Sequence is a 64-bit counter starting at 0, left-padded to 12 bytes."
            ),
            "aead": (
                "AES-128-GCM. The additional authenticated data (AAD) for each record "
                "is provided in the 'additional_data' field (the 5-byte record header)."
            ),
            "server_hello_key_share": (
                "The server's X25519 public key is in the key_share extension "
                "(type 0x0033) of the ServerHello. Parse the ServerHello handshake "
                "message to extract it."
            ),
        },
    }

    os.makedirs("/app", exist_ok=True)
    with open("/app/session_data.json", "w") as f:
        json.dump(session_data, f, indent=2)

    print("Session data written to /app/session_data.json")
    print(f"  Shared secret: {shared_secret.hex()}")
    print(f"  Server handshake key: {s_hs_key.hex()}")
    print(f"  Server app key: {s_ap_key.hex()}")


if __name__ == "__main__":
    main()
