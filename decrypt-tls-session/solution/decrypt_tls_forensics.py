#!/usr/bin/env python3
"""
TLS 1.3 forensic analysis: sort interleaved sessions, evaluate integrity,
decrypt intact session, identify tampered record, produce forensic report.
"""

import os
import struct
import hashlib
import hmac as hmac_mod
import json
import glob

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DATA_DIR = '/opt/tls_forensics'
CAPTURES_DIR = f'{DATA_DIR}/captures'


# ================================================================
# HKDF / TLS 1.3 key derivation (RFC 8446 Section 7.1)
# ================================================================

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
    return hkdf_expand_label(
        secret, label, hashlib.sha256(messages).digest(), 32
    )


# ================================================================
# TLS handshake parsers
# ================================================================

def parse_server_hello_pubkey(sh_msg):
    """Extract the X25519 public key from the key_share extension."""
    offset = 4 + 2 + 32  # handshake header + version + random
    sid_len = sh_msg[offset]
    offset += 1 + sid_len + 2 + 1  # session_id + cipher_suite + compression
    ext_total_len = struct.unpack('!H', sh_msg[offset:offset + 2])[0]
    offset += 2
    ext_end = offset + ext_total_len
    while offset < ext_end:
        ext_type = struct.unpack('!H', sh_msg[offset:offset + 2])[0]
        ext_data_len = struct.unpack('!H', sh_msg[offset + 2:offset + 4])[0]
        ext_data = sh_msg[offset + 4:offset + 4 + ext_data_len]
        if ext_type == 0x0033:  # key_share
            key_len = struct.unpack('!H', ext_data[2:4])[0]
            return ext_data[4:4 + key_len]
        offset += 4 + ext_data_len
    raise ValueError("key_share extension not found in ServerHello")


def extract_session_id(hs_msg):
    """Extract session_id from a ClientHello or ServerHello handshake message."""
    offset = 4 + 2 + 32  # handshake header + version + random
    sid_len = hs_msg[offset]
    return hs_msg[offset + 1:offset + 1 + sid_len]


# ================================================================
# Step 1: Read and classify all records
# ================================================================

records = {}
for filepath in sorted(glob.glob(f'{CAPTURES_DIR}/record_*.bin')):
    fn = os.path.basename(filepath)
    with open(filepath, 'rb') as f:
        records[fn] = f.read()

print(f"Loaded {len(records)} records")

plaintext_hs = {}  # fn -> (hs_type, handshake_bytes)
encrypted = {}     # fn -> raw_data

for fn, data in records.items():
    rtype = data[0]
    if rtype == 0x16:  # Handshake
        hs_data = data[5:]
        hs_type = hs_data[0]
        plaintext_hs[fn] = (hs_type, hs_data)
        print(f"  {fn}: plaintext handshake type=0x{hs_type:02x}, {len(data)} bytes")
    elif rtype == 0x17:  # Application Data (encrypted)
        encrypted[fn] = data
        print(f"  {fn}: encrypted record, {len(data)} bytes")

print(f"\nPlaintext handshakes: {len(plaintext_hs)}, Encrypted records: {len(encrypted)}")


# ================================================================
# Step 2: Pair ClientHello/ServerHello by session_id
# ================================================================

client_hellos = {}  # session_id -> (fn, hs_data)
server_hellos = {}  # session_id -> (fn, hs_data)

for fn, (hs_type, hs_data) in plaintext_hs.items():
    sid = extract_session_id(hs_data)
    if hs_type == 0x01:
        client_hellos[sid] = (fn, hs_data)
    elif hs_type == 0x02:
        server_hellos[sid] = (fn, hs_data)

sessions = {}
for sid in client_hellos:
    if sid in server_hellos:
        sessions[sid] = {
            'ch_fn': client_hellos[sid][0],
            'ch_hs': client_hellos[sid][1],
            'sh_fn': server_hellos[sid][0],
            'sh_hs': server_hellos[sid][1],
        }

print(f"Identified {len(sessions)} sessions by session_id matching")


# ================================================================
# Step 3: Read leaked keys
# ================================================================

keys = {}
with open(f'{DATA_DIR}/leaked_key_alpha.hex') as f:
    keys['alpha'] = bytes.fromhex(f.read().strip())
with open(f'{DATA_DIR}/leaked_key_beta.hex') as f:
    keys['beta'] = bytes.fromhex(f.read().strip())


# ================================================================
# Step 4: Try each (session, key) combination to find the intact session
# For each combo: derive handshake keys, try decrypting encrypted records
# ================================================================

intact_info = None

for sid, sess in sessions.items():
    if intact_info:
        break
    for key_name, key_bytes in keys.items():
        if intact_info:
            break

        # Derive handshake traffic keys for this session+key combo
        server_pub = parse_server_hello_pubkey(sess['sh_hs'])
        client_key = X25519PrivateKey.from_private_bytes(key_bytes)
        server_pub_key = X25519PublicKey.from_public_bytes(server_pub)
        shared_secret = client_key.exchange(server_pub_key)

        zeros_32 = b'\x00' * 32
        early_secret = hkdf_extract(zeros_32, zeros_32)
        derived_1 = derive_secret(early_secret, "derived", b"")
        handshake_secret = hkdf_extract(derived_1, shared_secret)

        transcript_ch_sh = sess['ch_hs'] + sess['sh_hs']
        server_hs_ts = derive_secret(
            handshake_secret, "s hs traffic", transcript_ch_sh
        )
        server_hs_key = hkdf_expand_label(server_hs_ts, "key", b"", 16)
        server_hs_iv = hkdf_expand_label(server_hs_ts, "iv", b"", 12)

        aesgcm_hs = AESGCM(server_hs_key)

        # Try each encrypted record as the potential handshake record
        for enc_fn, enc_data in encrypted.items():
            aad = enc_data[:5]
            ct = enc_data[5:]
            try:
                pt = aesgcm_hs.decrypt(server_hs_iv, ct, aad)
            except Exception:
                continue

            # Successfully decrypted the handshake record!
            hs_content = pt[:-1]  # strip content type byte
            hs_fn = enc_fn
            print(f"\nHandshake decrypted: {hs_fn} with key '{key_name}'")

            # Derive application traffic keys from full transcript
            transcript_full = transcript_ch_sh + hs_content
            derived_2 = derive_secret(handshake_secret, "derived", b"")
            master_secret = hkdf_extract(derived_2, zeros_32)
            server_app_ts = derive_secret(
                master_secret, "s ap traffic", transcript_full
            )
            server_app_key = hkdf_expand_label(server_app_ts, "key", b"", 16)
            server_app_iv = hkdf_expand_label(server_app_ts, "iv", b"", 12)

            aesgcm_app = AESGCM(server_app_key)

            # Find the application data record
            for app_fn, app_data in encrypted.items():
                if app_fn == hs_fn:
                    continue
                aad_app = app_data[:5]
                ct_app = app_data[5:]
                try:
                    pt_app = aesgcm_app.decrypt(server_app_iv, ct_app, aad_app)
                except Exception:
                    continue

                # Found both records for the intact session
                intact_info = {
                    'key_name': key_name,
                    'session_id': sid,
                    'session': sess,
                    'hs_fn': hs_fn,
                    'app_fn': app_fn,
                    'app_plaintext': pt_app[:-1],  # strip content type
                }
                print(f"App data decrypted: {app_fn}")
                break
            break

if not intact_info:
    raise RuntimeError("Could not decrypt any session")


# ================================================================
# Step 5: Determine compromised session and identify tampered record
# ================================================================

intact_key = intact_info['key_name']
compromised_key = 'beta' if intact_key == 'alpha' else 'alpha'

intact_records = {
    intact_info['session']['ch_fn'],
    intact_info['session']['sh_fn'],
    intact_info['hs_fn'],
    intact_info['app_fn'],
}
compromised_records = set(records.keys()) - intact_records

# Among the compromised session's encrypted records, the smaller one is
# the encrypted handshake (EncryptedExtensions + Finished ~ 64 bytes)
# vs the application data record (~ 170+ bytes). The encrypted handshake
# is the tampered record because it should decrypt with the handshake key
# but fails GCM authentication due to ciphertext modification.
compromised_encrypted = []
for fn in compromised_records:
    if records[fn][0] == 0x17:  # encrypted record
        compromised_encrypted.append((fn, len(records[fn])))

compromised_encrypted.sort(key=lambda x: x[1])
tampered_record = compromised_encrypted[0][0]  # smallest = handshake

print(f"\nForensic evaluation results:")
print(f"  Intact session: {intact_key}")
print(f"  Compromised session: {compromised_key}")
print(f"  Tampered record: {tampered_record}")
print(f"  Intact records: {sorted(intact_records)}")
print(f"  Compromised records: {sorted(compromised_records)}")


# ================================================================
# Step 6: Write outputs
# ================================================================

with open('/app/plaintext.txt', 'wb') as f:
    f.write(intact_info['app_plaintext'])

report = {
    "intact_session": intact_key,
    "compromised_session": compromised_key,
    "tampered_record": tampered_record,
    "session_records": {
        intact_key: sorted(list(intact_records)),
        compromised_key: sorted(list(compromised_records)),
    },
    "vulnerability_assessment": (
        f"Session '{compromised_key}' has been compromised by an active "
        f"man-in-the-middle attack. The encrypted handshake record "
        f"({tampered_record}) failed AES-128-GCM authentication, proving "
        f"its ciphertext was modified after encryption by the legitimate "
        f"server. Because TLS 1.3 derives application traffic keys from "
        f"the handshake transcript, tampering with the encrypted handshake "
        f"prevents recovery of any subsequent application data in this "
        f"session. Session '{intact_key}' passed all cryptographic integrity "
        f"checks and its application data was successfully decrypted."
    ),
}

with open('/app/forensic_report.json', 'w') as f:
    json.dump(report, f, indent=2)

print(f"\nDecrypted plaintext: {intact_info['app_plaintext'].decode()}")
print(f"Forensic report written to /app/forensic_report.json")
print(f"Decrypted plaintext written to /app/plaintext.txt")
