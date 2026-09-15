#!/usr/bin/env python3
"""Generate a synthetic TLS 1.3 session for the decryption task.

Creates binary files representing a TLS 1.3 handshake with known client
private key, so the agent can implement the key schedule and decrypt.
Cipher suite: TLS_AES_128_GCM_SHA256, key exchange: X25519, no PSK.
"""

import os
import struct
import hashlib
import hmac as hmac_mod

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization


def hmac_sha256(key, data):
    return hmac_mod.new(key, data, hashlib.sha256).digest()


def hkdf_extract(salt, ikm):
    return hmac_sha256(salt, ikm)


def hkdf_expand(prk, info, length):
    hash_len = 32
    n = (length + hash_len - 1) // hash_len
    okm = b''
    t = b''
    for i in range(1, n + 1):
        t = hmac_sha256(prk, t + info + bytes([i]))
        okm += t
    return okm[:length]


def hkdf_expand_label(secret, label, context, length):
    label_bytes = b'tls13 ' + (label.encode() if isinstance(label, str) else label)
    hkdf_label = struct.pack('!H', length)
    hkdf_label += struct.pack('!B', len(label_bytes)) + label_bytes
    hkdf_label += struct.pack('!B', len(context)) + context
    return hkdf_expand(secret, hkdf_label, length)


def derive_secret(secret, label, messages):
    return hkdf_expand_label(secret, label, hashlib.sha256(messages).digest(), 32)


# ============================================================
# Step 1: Generate X25519 key pairs
# ============================================================
client_private_key = X25519PrivateKey.generate()
client_private_bytes = client_private_key.private_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PrivateFormat.Raw,
    encryption_algorithm=serialization.NoEncryption()
)
client_public_bytes = client_private_key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw
)

server_private_key = X25519PrivateKey.generate()
server_public_bytes = server_private_key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw
)

# ECDH shared secret
shared_secret = client_private_key.exchange(server_private_key.public_key())

# ============================================================
# Step 2: Build ClientHello record
# ============================================================
client_random = os.urandom(32)
session_id = os.urandom(32)

# ClientHello extensions
extensions = b''

# supported_versions (0x002b)
sv_data = struct.pack('!B', 2) + struct.pack('!H', 0x0304)
extensions += struct.pack('!HH', 0x002b, len(sv_data)) + sv_data

# supported_groups (0x000a)
sg_data = struct.pack('!H', 2) + struct.pack('!H', 0x001d)
extensions += struct.pack('!HH', 0x000a, len(sg_data)) + sg_data

# signature_algorithms (0x000d)
sa_data = struct.pack('!H', 2) + struct.pack('!H', 0x0403)
extensions += struct.pack('!HH', 0x000d, len(sa_data)) + sa_data

# key_share (0x0033)
key_entry = struct.pack('!HH', 0x001d, 32) + client_public_bytes
ks_data = struct.pack('!H', len(key_entry)) + key_entry
extensions += struct.pack('!HH', 0x0033, len(ks_data)) + ks_data

# ClientHello body
ch_body = b''
ch_body += struct.pack('!H', 0x0303)       # legacy version TLS 1.2
ch_body += client_random                     # 32 bytes random
ch_body += struct.pack('!B', len(session_id)) + session_id
ch_body += struct.pack('!H', 2) + struct.pack('!H', 0x1301)  # cipher suites
ch_body += struct.pack('!B', 1) + b'\x00'   # compression methods

ch_body += struct.pack('!H', len(extensions)) + extensions

# Handshake message: type(1) + 3-byte length + body
ch_handshake = b'\x01' + struct.pack('!I', len(ch_body))[1:] + ch_body

# TLS record: type(1) + version(2) + length(2) + payload
ch_record = struct.pack('!BHH', 0x16, 0x0301, len(ch_handshake)) + ch_handshake

# ============================================================
# Step 3: Build ServerHello record
# ============================================================
server_random = os.urandom(32)

sh_extensions = b''

# supported_versions (0x002b) — ServerHello: no list wrapper
sh_sv_data = struct.pack('!H', 0x0304)
sh_extensions += struct.pack('!HH', 0x002b, len(sh_sv_data)) + sh_sv_data

# key_share (0x0033) — ServerHello: single entry, no list wrapper
sh_ks_data = struct.pack('!HH', 0x001d, 32) + server_public_bytes
sh_extensions += struct.pack('!HH', 0x0033, len(sh_ks_data)) + sh_ks_data

sh_body = b''
sh_body += struct.pack('!H', 0x0303)       # legacy version
sh_body += server_random                     # 32 bytes random
sh_body += struct.pack('!B', len(session_id)) + session_id  # echo session ID
sh_body += struct.pack('!H', 0x1301)        # cipher suite
sh_body += b'\x00'                           # compression method
sh_body += struct.pack('!H', len(sh_extensions)) + sh_extensions

sh_handshake = b'\x02' + struct.pack('!I', len(sh_body))[1:] + sh_body
sh_record = struct.pack('!BHH', 0x16, 0x0303, len(sh_handshake)) + sh_handshake

# ============================================================
# Step 4: Derive handshake traffic keys
# ============================================================
zeros_32 = b'\x00' * 32

early_secret = hkdf_extract(zeros_32, zeros_32)  # no PSK
derived_secret_1 = derive_secret(early_secret, "derived", b"")
handshake_secret = hkdf_extract(derived_secret_1, shared_secret)

transcript_ch_sh = ch_handshake + sh_handshake

server_hs_traffic_secret = derive_secret(handshake_secret, "s hs traffic", transcript_ch_sh)
server_hs_key = hkdf_expand_label(server_hs_traffic_secret, "key", b"", 16)
server_hs_iv = hkdf_expand_label(server_hs_traffic_secret, "iv", b"", 12)

# ============================================================
# Step 5: Build and encrypt server handshake
# ============================================================

# EncryptedExtensions (no extensions)
ee_body = struct.pack('!H', 0)  # extensions_length = 0
ee_msg = b'\x08' + struct.pack('!I', len(ee_body))[1:] + ee_body

# Finished message
finished_key = hkdf_expand_label(server_hs_traffic_secret, "finished", b"", 32)
transcript_for_finished = transcript_ch_sh + ee_msg
verify_data = hmac_sha256(finished_key, hashlib.sha256(transcript_for_finished).digest())
finished_msg = b'\x14' + struct.pack('!I', len(verify_data))[1:] + verify_data

# Inner plaintext: handshake messages + content type byte (0x16 = handshake)
hs_inner_plaintext = ee_msg + finished_msg + b'\x16'

# Encrypt with AES-128-GCM (sequence number 0, so nonce = IV)
aesgcm_hs = AESGCM(server_hs_key)
ciphertext_hs_len = len(hs_inner_plaintext) + 16  # +16 for GCM tag
aad_hs = struct.pack('!BHH', 0x17, 0x0303, ciphertext_hs_len)
ciphertext_hs = aesgcm_hs.encrypt(server_hs_iv, hs_inner_plaintext, aad_hs)

encrypted_hs_record = aad_hs + ciphertext_hs

# ============================================================
# Step 6: Derive application traffic keys
# ============================================================
transcript_ch_sf = transcript_ch_sh + ee_msg + finished_msg

derived_secret_2 = derive_secret(handshake_secret, "derived", b"")
master_secret = hkdf_extract(derived_secret_2, zeros_32)

server_app_traffic_secret = derive_secret(master_secret, "s ap traffic", transcript_ch_sf)
server_app_key = hkdf_expand_label(server_app_traffic_secret, "key", b"", 16)
server_app_iv = hkdf_expand_label(server_app_traffic_secret, "iv", b"", 12)

# ============================================================
# Step 7: Encrypt application data
# ============================================================
flag_token = os.urandom(20).hex()
app_plaintext = f"FLAG{{tls13_{flag_token}}}".encode()

# Inner plaintext: content + content type byte (0x17 = application_data)
app_inner_plaintext = app_plaintext + b'\x17'

aesgcm_app = AESGCM(server_app_key)
ciphertext_app_len = len(app_inner_plaintext) + 16
aad_app = struct.pack('!BHH', 0x17, 0x0303, ciphertext_app_len)
ciphertext_app = aesgcm_app.encrypt(server_app_iv, app_inner_plaintext, aad_app)

encrypted_app_record = aad_app + ciphertext_app

# ============================================================
# Step 8: Save all files to /opt/tls_challenge (not /app)
# ============================================================
DATA_DIR = '/opt/tls_challenge'
os.makedirs(DATA_DIR, exist_ok=True)

with open(f'{DATA_DIR}/capture_0.bin', 'wb') as f:
    f.write(ch_record)

with open(f'{DATA_DIR}/capture_1.bin', 'wb') as f:
    f.write(sh_record)

with open(f'{DATA_DIR}/capture_2.bin', 'wb') as f:
    f.write(encrypted_hs_record)

with open(f'{DATA_DIR}/capture_3.bin', 'wb') as f:
    f.write(encrypted_app_record)

with open(f'{DATA_DIR}/session_key.hex', 'w') as f:
    f.write(client_private_bytes.hex())

# Verification hash (SHA-256 of expected plaintext output)
expected_hash = hashlib.sha256(app_plaintext).hexdigest()
with open(f'{DATA_DIR}/.verification_hash', 'w') as f:
    f.write(expected_hash)

print(f"TLS 1.3 session generated successfully in {DATA_DIR}/")
print(f"capture_0.bin (ClientHello): {len(ch_record)} bytes")
print(f"capture_1.bin (ServerHello): {len(sh_record)} bytes")
print(f"capture_2.bin (encrypted handshake): {len(encrypted_hs_record)} bytes")
print(f"capture_3.bin (encrypted app data): {len(encrypted_app_record)} bytes")
print(f"Verification hash: {expected_hash}")
