#!/usr/bin/env python3
"""Initialize the SQLite database with users and encrypted restricted credentials."""

import hashlib
import sqlite3
import os
import subprocess

DB_PATH = '/app/database.db'
SEED = 'waf-bypass-ctf-2024'
SALT = 'k8s-waf-deploy-2024-prod-salt'


def gen_credential(n):
    h = hashlib.sha256(f"{SEED}-credential-{n}".encode()).hexdigest()[:24]
    return f"FLAG{{{h}}}"


def encrypt_credential(plaintext, key_hex, iv_hex):
    """Encrypt using openssl CLI to ensure decryption compatibility."""
    result = subprocess.run(
        ['openssl', 'enc', '-aes-256-cbc', '-a', '-A',
         '-K', key_hex, '-iv', iv_hex, '-nosalt'],
        input=plaintext.encode(),
        capture_output=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Encryption failed: {result.stderr.decode()}")
    return result.stdout.decode().strip()


def init():
    os.makedirs('/app', exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL,
        email TEXT NOT NULL,
        role TEXT NOT NULL,
        department TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE internal_credentials (
        id INTEGER PRIMARY KEY,
        category TEXT NOT NULL,
        credential_blob TEXT NOT NULL,
        iv_hex TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE encryption_metadata (
        id INTEGER PRIMARY KEY,
        key_name TEXT NOT NULL,
        salt_value TEXT NOT NULL,
        algorithm TEXT NOT NULL,
        notes TEXT
    )''')

    users = [
        (1, 'admin', 'admin@corp.local', 'admin', 'IT'),
        (2, 'jdoe', 'jdoe@corp.local', 'user', 'Engineering'),
        (3, 'asmith', 'asmith@corp.local', 'user', 'Marketing'),
        (4, 'bwilson', 'bwilson@corp.local', 'manager', 'Engineering'),
        (5, 'cjones', 'cjones@corp.local', 'user', 'HR'),
    ]
    c.executemany('INSERT INTO users VALUES (?,?,?,?,?)', users)

    key_hex = hashlib.sha256(SALT.encode()).hexdigest()

    categories = ['api_key', 'db_password', 'jwt_secret', 'encryption_key']
    for i in range(1, 5):
        plaintext = gen_credential(i)
        iv_hex = hashlib.md5(f"{SEED}-iv-{i}".encode()).hexdigest()
        encrypted = encrypt_credential(plaintext, key_hex, iv_hex)
        c.execute('INSERT INTO internal_credentials VALUES (?,?,?,?)',
                  (i, categories[i - 1], encrypted, iv_hex))

    c.execute('INSERT INTO encryption_metadata VALUES (?,?,?,?,?)',
              (1, 'credential_key', SALT, 'aes-256-cbc',
               'Key derivation: SHA-256 of salt_value. IVs stored per row in iv_hex column.'))

    conn.commit()
    conn.close()


if __name__ == '__main__':
    init()
