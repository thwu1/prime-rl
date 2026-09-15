#!/usr/bin/env python3
"""Setup the Vinaigrette challenge environment.

Generates a TLS certificate, encrypts the public key using a passphrase
derived from the certificate fingerprint, and creates a SQLite configuration
database with scheme parameters and key management metadata.
"""
import subprocess
import sqlite3
import os

# Generate self-signed TLS certificate
os.makedirs('/app/certs', exist_ok=True)
subprocess.run([
    'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
    '-keyout', '/app/certs/service.key',
    '-out', '/app/certs/service.crt',
    '-days', '365', '-nodes',
    '-subj', '/CN=vinaigrette.local/O=CryptoLab/C=DE'
], check=True, capture_output=True)

# Get SHA-256 fingerprint of the certificate
result = subprocess.run(
    ['openssl', 'x509', '-in', '/app/certs/service.crt',
     '-fingerprint', '-sha256', '-noout'],
    capture_output=True, text=True, check=True
)
fingerprint_line = result.stdout.strip()
hex_part = fingerprint_line.split('=', 1)[1]
passphrase = hex_part.replace(':', '').lower()

# Encrypt public key with AES-256-CBC using PBKDF2
subprocess.run([
    'openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-iter', '100000',
    '-salt',
    '-in', '/tmp/public_key_raw.txt',
    '-out', '/app/pubkey.enc',
    '-pass', 'pass:' + passphrase
], check=True)

# Create SQLite configuration database
conn = sqlite3.connect('/app/vinaigrette.db')
c = conn.cursor()

c.execute('''CREATE TABLE scheme_params (
    param_name TEXT PRIMARY KEY,
    param_value INTEGER NOT NULL
)''')

c.execute('''CREATE TABLE key_management (
    property TEXT PRIMARY KEY,
    value TEXT NOT NULL
)''')

c.execute('''CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    content TEXT NOT NULL,
    purpose TEXT NOT NULL
)''')

# Scheme parameters
for name, val in [('q', 31), ('n', 12), ('m', 8), ('o', 6), ('k', 2)]:
    c.execute('INSERT INTO scheme_params VALUES (?, ?)', (name, val))

# Key management configuration
key_mgmt = [
    ('pubkey_file', '/app/pubkey.enc'),
    ('encryption_cipher', 'aes-256-cbc'),
    ('kdf_algorithm', 'pbkdf2'),
    ('kdf_iterations', '100000'),
    ('passphrase_source', 'tls_certificate_fingerprint'),
    ('fingerprint_hash', 'sha256'),
    ('fingerprint_format', 'hex_lowercase_no_separators'),
    ('cert_path', '/app/certs/service.crt'),
]
for prop, val in key_mgmt:
    c.execute('INSERT INTO key_management VALUES (?, ?)', (prop, val))

# Target message
c.execute('INSERT INTO messages VALUES (?, ?, ?)',
          (1, 'Forge this Vinaigrette signature', 'signing_target'))

conn.commit()
conn.close()

print("Environment setup complete")
