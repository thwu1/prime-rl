#!/usr/bin/env python3
"""
Convert data.json into a multi-format ECDSA signature corpus:
  - SQLite database with metadata and relationships
  - PEM-encoded EC public key files (SubjectPublicKeyInfo)
  - DER-encoded ECDSA signature files (ASN.1 SEQUENCE { INTEGER r, INTEGER s })

This script runs at Docker build time and is removed afterward.
"""

import json
import os
import sqlite3
import base64


def der_length(length):
    if length < 0x80:
        return bytes([length])
    elif length < 0x100:
        return bytes([0x81, length])
    else:
        return bytes([0x82, (length >> 8) & 0xff, length & 0xff])


def der_integer(value):
    """Encode a non-negative integer in DER (minimal, positive)."""
    if value == 0:
        return b'\x02\x01\x00'
    byte_len = (value.bit_length() + 7) // 8
    b = value.to_bytes(byte_len, 'big')
    if b[0] & 0x80:
        b = b'\x00' + b
    return b'\x02' + der_length(len(b)) + b


def der_sequence(contents):
    return b'\x30' + der_length(len(contents)) + contents


def encode_ecdsa_sig_der(r_hex, s_hex):
    """Encode (r, s) as a DER-encoded ECDSA signature."""
    r = int(r_hex, 16)
    s = int(s_hex, 16)
    return der_sequence(der_integer(r) + der_integer(s))


def encode_ec_pubkey_pem(compressed_hex):
    """
    Encode a compressed secp256k1 EC public key as PEM SubjectPublicKeyInfo.

    ASN.1 structure:
      SubjectPublicKeyInfo ::= SEQUENCE {
        algorithm  AlgorithmIdentifier ::= SEQUENCE {
          algorithm   OID (1.2.840.10045.2.1 = ecPublicKey),
          parameters  OID (1.3.132.0.10 = secp256k1)
        },
        subjectPublicKey  BIT STRING
      }
    """
    key_bytes = bytes.fromhex(compressed_hex)
    assert len(key_bytes) == 33, f"Expected 33-byte compressed key, got {len(key_bytes)}"

    # OID encodings (tag + length + value)
    ec_oid = bytes.fromhex('06072a8648ce3d0201')      # ecPublicKey 1.2.840.10045.2.1
    curve_oid = bytes.fromhex('06052b8104000a')         # secp256k1   1.3.132.0.10

    # AlgorithmIdentifier SEQUENCE
    algo_content = ec_oid + curve_oid                   # 16 bytes
    algo_id = b'\x30' + bytes([len(algo_content)]) + algo_content  # 18 bytes

    # BIT STRING: tag 0x03, length, 0x00 (unused bits), key bytes
    bit_content = b'\x00' + key_bytes                   # 34 bytes
    bit_string = b'\x03' + bytes([len(bit_content)]) + bit_content  # 36 bytes

    # Outer SEQUENCE
    spki_content = algo_id + bit_string                 # 54 bytes
    spki = b'\x30' + bytes([len(spki_content)]) + spki_content     # 56 bytes

    # PEM encode
    b64 = base64.b64encode(spki).decode('ascii')
    lines = [b64[i:i+64] for i in range(0, len(b64), 64)]
    return '-----BEGIN PUBLIC KEY-----\n' + '\n'.join(lines) + '\n-----END PUBLIC KEY-----\n'


def main():
    with open('/tmp/data.json', 'r') as f:
        data = json.load(f)

    os.makedirs('/app/keys', exist_ok=True)
    os.makedirs('/app/sigs', exist_ok=True)

    # Assign key IDs in order of first appearance
    pubkey_order = []
    seen = set()
    for sig in data['signatures']:
        pk = sig['public_key']
        if pk not in seen:
            seen.add(pk)
            pubkey_order.append(pk)

    key_id_map = {}  # compressed_hex -> (key_id, pem_filename)
    aliases = ['alpha', 'bravo', 'charlie']

    for idx, pk_hex in enumerate(pubkey_order):
        key_id = idx + 1
        filename = f'key_{key_id}.pem'
        pem = encode_ec_pubkey_pem(pk_hex)
        with open(f'/app/keys/{filename}', 'w') as f:
            f.write(pem)
        key_id_map[pk_hex] = (key_id, filename)

    # Write DER signature files
    sig_records = []
    for i, sig in enumerate(data['signatures']):
        sig_id = i + 1
        der = encode_ecdsa_sig_der(sig['signature_r'], sig['signature_s'])
        filename = f'sig_{sig_id:02d}.der'
        with open(f'/app/sigs/{filename}', 'wb') as f:
            f.write(der)
        sig_records.append((sig_id, sig, filename))

    # Create SQLite database
    db = sqlite3.connect('/app/corpus.db')
    c = db.cursor()

    c.execute('''CREATE TABLE ec_keys (
        key_id    INTEGER PRIMARY KEY,
        alias     TEXT    NOT NULL,
        pem_file  TEXT    NOT NULL,
        curve     TEXT    NOT NULL DEFAULT 'secp256k1'
    )''')

    c.execute('''CREATE TABLE ecdsa_signatures (
        sig_id        INTEGER PRIMARY KEY,
        key_id        INTEGER NOT NULL REFERENCES ec_keys(key_id),
        message_hash  TEXT    NOT NULL,
        der_file      TEXT    NOT NULL,
        recovery_id   INTEGER,
        tx_index      INTEGER
    )''')

    c.execute('''CREATE TABLE signing_challenges (
        challenge_id  INTEGER PRIMARY KEY,
        key_id        INTEGER NOT NULL REFERENCES ec_keys(key_id),
        message_hash  TEXT    NOT NULL
    )''')

    for pk_hex, (key_id, filename) in key_id_map.items():
        alias = aliases[key_id - 1]
        c.execute('INSERT INTO ec_keys VALUES (?, ?, ?, ?)',
                  (key_id, alias, filename, 'secp256k1'))

    for sig_id, sig, filename in sig_records:
        pk_hex = sig['public_key']
        key_id = key_id_map[pk_hex][0]
        c.execute('INSERT INTO ecdsa_signatures VALUES (?, ?, ?, ?, ?, ?)',
                  (sig_id, key_id, sig['message_hash'], filename,
                   sig.get('recovery_id'), sig_id))

    for i, ch in enumerate(data['challenges']):
        pk_hex = ch['target_public_key']
        key_id = key_id_map[pk_hex][0]
        c.execute('INSERT INTO signing_challenges VALUES (?, ?, ?)',
                  (i + 1, key_id, ch['message_hash']))

    db.commit()
    db.close()

    print(f"Corpus created: {len(key_id_map)} keys, {len(sig_records)} sigs, "
          f"{len(data['challenges'])} challenges")


if __name__ == '__main__':
    main()
