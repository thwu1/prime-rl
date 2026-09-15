#!/usr/bin/env python3
"""
TLS 1.3 session decryption.

Implements the TLS 1.3 key schedule (RFC 8446 Section 7) to decrypt a
captured session. Uses the cryptography library for X25519 ECDH and
AES-128-GCM primitives; HKDF and the TLS 1.3 label/secret derivation
are implemented from scratch.
"""

import struct
import hashlib
import hmac as hmac_mod

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization

DATA_DIR = '/opt/tls_challenge'

# ================================================================
# HKDF and TLS 1.3 key derivation primitives
# ================================================================

def hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac_mod.new(key, data, hashlib.sha256).digest()


def hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    """HKDF-Extract (RFC 5869): PRK = HMAC-Hash(salt, IKM)."""
    return hmac_sha256(salt, ikm)


def hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    """HKDF-Expand (RFC 5869)."""
    hash_len = 32  # SHA-256 output
    n = (length + hash_len - 1) // hash_len
    okm = b''
    t = b''
    for i in range(1, n + 1):
        t = hmac_sha256(prk, t + info + bytes([i]))
        okm += t
    return okm[:length]


def hkdf_expand_label(secret: bytes, label: str, context: bytes,
                       length: int) -> bytes:
    """TLS 1.3 HKDF-Expand-Label (RFC 8446 Section 7.1)."""
    label_bytes = b'tls13 ' + label.encode()
    hkdf_label = struct.pack('!H', length)
    hkdf_label += struct.pack('!B', len(label_bytes)) + label_bytes
    hkdf_label += struct.pack('!B', len(context)) + context
    return hkdf_expand(secret, hkdf_label, length)


def derive_secret(secret: bytes, label: str, messages: bytes) -> bytes:
    """TLS 1.3 Derive-Secret (RFC 8446 Section 7.1)."""
    return hkdf_expand_label(
        secret, label, hashlib.sha256(messages).digest(), 32
    )


# ================================================================
# Read input files
# ================================================================

with open(f'{DATA_DIR}/capture_0.bin', 'rb') as f:
    ch_record = f.read()

with open(f'{DATA_DIR}/capture_1.bin', 'rb') as f:
    sh_record = f.read()

with open(f'{DATA_DIR}/capture_2.bin', 'rb') as f:
    enc_hs_record = f.read()

with open(f'{DATA_DIR}/capture_3.bin', 'rb') as f:
    enc_app_record = f.read()

with open(f'{DATA_DIR}/session_key.hex', 'r') as f:
    client_private_hex = f.read().strip()


# ================================================================
# Extract handshake messages (strip 5-byte record headers)
# ================================================================

ch_handshake = ch_record[5:]
sh_handshake = sh_record[5:]


# ================================================================
# Parse ServerHello to extract server's X25519 public key
# ================================================================

def parse_server_hello_pubkey(sh_msg: bytes) -> bytes:
    """Extract the X25519 public key from the key_share extension."""
    offset = 4   # skip handshake header (type + 3-byte length)
    offset += 2  # legacy_version
    offset += 32 # server_random
    sid_len = sh_msg[offset]
    offset += 1 + sid_len   # session_id_length + session_id
    offset += 2             # cipher_suite
    offset += 1             # compression_method
    ext_total_len = struct.unpack('!H', sh_msg[offset:offset + 2])[0]
    offset += 2

    ext_end = offset + ext_total_len
    while offset < ext_end:
        ext_type = struct.unpack('!H', sh_msg[offset:offset + 2])[0]
        ext_data_len = struct.unpack('!H', sh_msg[offset + 2:offset + 4])[0]
        ext_data = sh_msg[offset + 4:offset + 4 + ext_data_len]

        if ext_type == 0x0033:  # key_share
            # ServerHello key_share: NamedGroup(2) + KeyExchangeLen(2) + Key
            key_len = struct.unpack('!H', ext_data[2:4])[0]
            return ext_data[4:4 + key_len]

        offset += 4 + ext_data_len

    raise ValueError("key_share extension (0x0033) not found in ServerHello")


server_public_bytes = parse_server_hello_pubkey(sh_handshake)
print(f"Server public key: {server_public_bytes.hex()}")


# ================================================================
# Compute ECDH shared secret
# ================================================================

client_private_bytes = bytes.fromhex(client_private_hex)
client_private_key = X25519PrivateKey.from_private_bytes(client_private_bytes)
server_public_key = X25519PublicKey.from_public_bytes(server_public_bytes)
shared_secret = client_private_key.exchange(server_public_key)
print(f"Shared secret: {shared_secret.hex()}")


# ================================================================
# Derive handshake traffic keys
# ================================================================

zeros_32 = b'\x00' * 32

# Early secret (no PSK -> ikm = 0^32)
early_secret = hkdf_extract(salt=zeros_32, ikm=zeros_32)

# Handshake secret
derived_1 = derive_secret(early_secret, "derived", b"")
handshake_secret = hkdf_extract(salt=derived_1, ikm=shared_secret)

# Server handshake traffic secret
transcript_ch_sh = ch_handshake + sh_handshake
server_hs_traffic_secret = derive_secret(
    handshake_secret, "s hs traffic", transcript_ch_sh
)

# AES-128-GCM key and IV for server handshake
server_hs_key = hkdf_expand_label(server_hs_traffic_secret, "key", b"", 16)
server_hs_iv = hkdf_expand_label(server_hs_traffic_secret, "iv", b"", 12)

print(f"Server HS key: {server_hs_key.hex()}")
print(f"Server HS IV:  {server_hs_iv.hex()}")


# ================================================================
# Decrypt server handshake record
# ================================================================

aad_hs = enc_hs_record[:5]        # 5-byte record header = AAD
ciphertext_hs = enc_hs_record[5:]  # ciphertext + GCM tag

aesgcm_hs = AESGCM(server_hs_key)
# Nonce for sequence 0: IV XOR 0 = IV
plaintext_hs = aesgcm_hs.decrypt(server_hs_iv, ciphertext_hs, aad_hs)

# Strip the trailing content-type byte
hs_content_type = plaintext_hs[-1]
handshake_content = plaintext_hs[:-1]
print(f"Decrypted handshake: {len(handshake_content)} bytes, "
      f"inner content type: 0x{hs_content_type:02x}")


# ================================================================
# Derive application traffic keys
# ================================================================

# Full transcript: ClientHello + ServerHello + decrypted handshake messages
# (EncryptedExtensions + Finished)
transcript_ch_sf = transcript_ch_sh + handshake_content

# Master secret
derived_2 = derive_secret(handshake_secret, "derived", b"")
master_secret = hkdf_extract(salt=derived_2, ikm=zeros_32)

# Server application traffic secret
server_app_traffic_secret = derive_secret(
    master_secret, "s ap traffic", transcript_ch_sf
)

# AES-128-GCM key and IV for server application data
server_app_key = hkdf_expand_label(server_app_traffic_secret, "key", b"", 16)
server_app_iv = hkdf_expand_label(server_app_traffic_secret, "iv", b"", 12)

print(f"Server App key: {server_app_key.hex()}")
print(f"Server App IV:  {server_app_iv.hex()}")


# ================================================================
# Decrypt application data record
# ================================================================

aad_app = enc_app_record[:5]
ciphertext_app = enc_app_record[5:]

aesgcm_app = AESGCM(server_app_key)
# Nonce for sequence 0: IV XOR 0 = IV
plaintext_app = aesgcm_app.decrypt(server_app_iv, ciphertext_app, aad_app)

# Strip the trailing content-type byte
app_content = plaintext_app[:-1]


# ================================================================
# Write output
# ================================================================

with open('/app/output.txt', 'wb') as f:
    f.write(app_content)

print(f"Decrypted application data: {app_content.decode()}")
print("Written to /app/output.txt")
