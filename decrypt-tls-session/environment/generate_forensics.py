#!/usr/bin/env python3
"""Generate two interleaved TLS 1.3 sessions for forensic analysis.

Creates 8 binary TLS records from two sessions (Alpha and Beta), shuffled
so sessions are interleaved. Beta's encrypted handshake is tampered with
(byte flip in GCM ciphertext), causing authentication failure on decryption.

No verification data is written — tests verify through computation.
"""

import os
import struct
import hashlib
import hmac as hmac_mod
import random

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


def generate_session(app_plaintext_str):
    """Generate a complete TLS 1.3 session with all records and key material."""
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

    shared_secret = client_private_key.exchange(server_private_key.public_key())

    # === ClientHello ===
    client_random = os.urandom(32)
    session_id = os.urandom(32)

    extensions = b''
    sv_data = struct.pack('!B', 2) + struct.pack('!H', 0x0304)
    extensions += struct.pack('!HH', 0x002b, len(sv_data)) + sv_data
    sg_data = struct.pack('!H', 2) + struct.pack('!H', 0x001d)
    extensions += struct.pack('!HH', 0x000a, len(sg_data)) + sg_data
    sa_data = struct.pack('!H', 2) + struct.pack('!H', 0x0403)
    extensions += struct.pack('!HH', 0x000d, len(sa_data)) + sa_data
    key_entry = struct.pack('!HH', 0x001d, 32) + client_public_bytes
    ks_data = struct.pack('!H', len(key_entry)) + key_entry
    extensions += struct.pack('!HH', 0x0033, len(ks_data)) + ks_data

    ch_body = struct.pack('!H', 0x0303) + client_random
    ch_body += struct.pack('!B', len(session_id)) + session_id
    ch_body += struct.pack('!H', 2) + struct.pack('!H', 0x1301)
    ch_body += struct.pack('!B', 1) + b'\x00'
    ch_body += struct.pack('!H', len(extensions)) + extensions

    ch_handshake = b'\x01' + struct.pack('!I', len(ch_body))[1:] + ch_body
    ch_record = struct.pack('!BHH', 0x16, 0x0301, len(ch_handshake)) + ch_handshake

    # === ServerHello ===
    server_random = os.urandom(32)

    sh_extensions = b''
    sh_sv_data = struct.pack('!H', 0x0304)
    sh_extensions += struct.pack('!HH', 0x002b, len(sh_sv_data)) + sh_sv_data
    sh_ks_data = struct.pack('!HH', 0x001d, 32) + server_public_bytes
    sh_extensions += struct.pack('!HH', 0x0033, len(sh_ks_data)) + sh_ks_data

    sh_body = struct.pack('!H', 0x0303) + server_random
    sh_body += struct.pack('!B', len(session_id)) + session_id
    sh_body += struct.pack('!H', 0x1301)
    sh_body += b'\x00'
    sh_body += struct.pack('!H', len(sh_extensions)) + sh_extensions

    sh_handshake = b'\x02' + struct.pack('!I', len(sh_body))[1:] + sh_body
    sh_record = struct.pack('!BHH', 0x16, 0x0303, len(sh_handshake)) + sh_handshake

    # === Derive handshake traffic keys ===
    zeros_32 = b'\x00' * 32
    early_secret = hkdf_extract(zeros_32, zeros_32)
    derived_1 = derive_secret(early_secret, "derived", b"")
    handshake_secret = hkdf_extract(derived_1, shared_secret)

    transcript_ch_sh = ch_handshake + sh_handshake
    server_hs_traffic_secret = derive_secret(
        handshake_secret, "s hs traffic", transcript_ch_sh
    )
    server_hs_key = hkdf_expand_label(server_hs_traffic_secret, "key", b"", 16)
    server_hs_iv = hkdf_expand_label(server_hs_traffic_secret, "iv", b"", 12)

    # === Encrypted handshake (EncryptedExtensions + Finished) ===
    ee_body = struct.pack('!H', 0)
    ee_msg = b'\x08' + struct.pack('!I', len(ee_body))[1:] + ee_body

    finished_key = hkdf_expand_label(
        server_hs_traffic_secret, "finished", b"", 32
    )
    transcript_for_finished = transcript_ch_sh + ee_msg
    verify_data = hmac_sha256(
        finished_key, hashlib.sha256(transcript_for_finished).digest()
    )
    finished_msg = b'\x14' + struct.pack('!I', len(verify_data))[1:] + verify_data

    hs_inner_plaintext = ee_msg + finished_msg + b'\x16'

    aesgcm_hs = AESGCM(server_hs_key)
    ciphertext_hs_len = len(hs_inner_plaintext) + 16
    aad_hs = struct.pack('!BHH', 0x17, 0x0303, ciphertext_hs_len)
    ciphertext_hs = aesgcm_hs.encrypt(server_hs_iv, hs_inner_plaintext, aad_hs)
    enc_hs_record = aad_hs + ciphertext_hs

    # === Derive application traffic keys ===
    transcript_ch_sf = transcript_ch_sh + ee_msg + finished_msg
    derived_2 = derive_secret(handshake_secret, "derived", b"")
    master_secret = hkdf_extract(derived_2, zeros_32)
    server_app_traffic_secret = derive_secret(
        master_secret, "s ap traffic", transcript_ch_sf
    )
    server_app_key = hkdf_expand_label(server_app_traffic_secret, "key", b"", 16)
    server_app_iv = hkdf_expand_label(server_app_traffic_secret, "iv", b"", 12)

    # === Encrypt application data ===
    app_plaintext = app_plaintext_str.encode()
    app_inner_plaintext = app_plaintext + b'\x17'

    aesgcm_app = AESGCM(server_app_key)
    ciphertext_app_len = len(app_inner_plaintext) + 16
    aad_app = struct.pack('!BHH', 0x17, 0x0303, ciphertext_app_len)
    ciphertext_app = aesgcm_app.encrypt(
        server_app_iv, app_inner_plaintext, aad_app
    )
    enc_app_record = aad_app + ciphertext_app

    return {
        'ch_record': ch_record,
        'sh_record': sh_record,
        'enc_hs_record': enc_hs_record,
        'enc_app_record': enc_app_record,
        'client_private_bytes': client_private_bytes,
        'app_plaintext': app_plaintext,
    }


# ============================================================
# Generate both sessions with random unique plaintexts
# ============================================================
alpha_token = os.urandom(20).hex()
beta_token = os.urandom(20).hex()

alpha = generate_session(
    "CONFIDENTIAL TRANSMISSION\n"
    "Session: alpha\n"
    f"Auth-Token: FLAG{{alpha_{alpha_token}}}\n"
    "Classification: TOP SECRET\n"
    "End of transmission."
)
beta = generate_session(
    "CONFIDENTIAL TRANSMISSION\n"
    "Session: beta\n"
    f"Auth-Token: FLAG{{beta_{beta_token}}}\n"
    "Classification: TOP SECRET\n"
    "End of transmission."
)

# Tamper with Beta's encrypted handshake: flip one byte in GCM ciphertext
tampered = bytearray(beta['enc_hs_record'])
tampered[10] ^= 0x01
beta['enc_hs_record'] = bytes(tampered)

# ============================================================
# Assign records to randomized filenames
# The order is shuffled at build time so it varies per image build
# ============================================================
DATA_DIR = '/opt/tls_forensics'
CAPTURES_DIR = f'{DATA_DIR}/captures'
os.makedirs(CAPTURES_DIR, exist_ok=True)

all_records = [
    ('alpha', 'ch', alpha['ch_record']),
    ('alpha', 'sh', alpha['sh_record']),
    ('alpha', 'enc_hs', alpha['enc_hs_record']),
    ('alpha', 'enc_app', alpha['enc_app_record']),
    ('beta', 'ch', beta['ch_record']),
    ('beta', 'sh', beta['sh_record']),
    ('beta', 'enc_hs', beta['enc_hs_record']),
    ('beta', 'enc_app', beta['enc_app_record']),
]

# Shuffle the assignment order so record_XX.bin numbering is random per build
random.shuffle(all_records)

for idx, (session, rtype, data) in enumerate(all_records):
    filename = f'record_{idx:02d}.bin'
    with open(f'{CAPTURES_DIR}/{filename}', 'wb') as f:
        f.write(data)

# Write leaked keys
with open(f'{DATA_DIR}/leaked_key_alpha.hex', 'w') as f:
    f.write(alpha['client_private_bytes'].hex())
with open(f'{DATA_DIR}/leaked_key_beta.hex', 'w') as f:
    f.write(beta['client_private_bytes'].hex())

# NO verification data is written to the image.
# Tests verify through computational re-derivation.

print(f"TLS 1.3 forensics challenge generated in {DATA_DIR}/")
for idx in range(8):
    fn = f'record_{idx:02d}.bin'
    with open(f'{CAPTURES_DIR}/{fn}', 'rb') as f:
        sz = len(f.read())
    print(f"  {fn}: {sz} bytes")
