#!/usr/bin/env python3
"""
Migration tool: decrypts all v1 (AES-128-ECB) entries and re-encrypts
them under the SecureEngine (AES-256-GCM + HKDF).
"""

import os
import sqlite3
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from secure_engine import SecureEngine

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

DB_PATH = '/app/data/audit.db'
KEY_FILE = '/app/remediation/migration_key.bin'
CONTEXT = 'v1-migration'


def unwrap_v1_key():
    result = subprocess.run([
        'openssl', 'pkeyutl', '-decrypt',
        '-inkey', '/app/keys/vault_priv.pem',
        '-passin', 'pass:vault-hsm-export-2024',
        '-pkeyopt', 'rsa_padding_mode:oaep',
        '-pkeyopt', 'rsa_oaep_md:sha256',
        '-pkeyopt', 'rsa_mgf1_md:sha256',
        '-in', '/app/keys/v1_wrapped.bin',
        '-out', '/tmp/v1_key_migrate.bin',
    ], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError("Failed to unwrap v1 key")
    with open('/tmp/v1_key_migrate.bin', 'rb') as f:
        return f.read()


def decrypt_ecb(key, ciphertext):
    cipher = Cipher(algorithms.AES128(key), modes.ECB())
    dec = cipher.decryptor()
    padded = dec.update(ciphertext) + dec.finalize()
    unpadder = PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def main():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, 'rb') as f:
            master_key = f.read()
    else:
        master_key = os.urandom(32)
        os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
        with open(KEY_FILE, 'wb') as f:
            f.write(master_key)

    engine = SecureEngine(master_key, CONTEXT)
    v1_key = unwrap_v1_key()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS migrated_entries (
        original_id INTEGER PRIMARY KEY,
        ciphertext  BLOB NOT NULL
    )""")

    cur = conn.execute(
        "SELECT id, ciphertext FROM log_entries WHERE engine_version = 1"
    )
    count = 0
    for row_id, ct in cur.fetchall():
        plaintext = decrypt_ecb(v1_key, ct)
        new_ct = engine.encrypt(plaintext)
        conn.execute(
            "INSERT OR REPLACE INTO migrated_entries "
            "(original_id, ciphertext) VALUES (?, ?)",
            (row_id, new_ct),
        )
        count += 1

    conn.commit()
    conn.close()
    print(f"Migrated {count} v1 entries to SecureEngine")


if __name__ == '__main__':
    main()
