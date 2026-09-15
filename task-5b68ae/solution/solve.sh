#!/bin/bash

cd /app

# === Step 1: Extract configuration from SQLite database ===
CERT_PATH=$(sqlite3 /app/vinaigrette.db "SELECT value FROM key_management WHERE property='cert_path';")
KDF_ITER=$(sqlite3 /app/vinaigrette.db "SELECT value FROM key_management WHERE property='kdf_iterations';")
PUBKEY_FILE=$(sqlite3 /app/vinaigrette.db "SELECT value FROM key_management WHERE property='pubkey_file';")
ENC_CIPHER=$(sqlite3 /app/vinaigrette.db "SELECT value FROM key_management WHERE property='encryption_cipher';")
FP_HASH=$(sqlite3 /app/vinaigrette.db "SELECT value FROM key_management WHERE property='fingerprint_hash';")

echo "Config: cipher=$ENC_CIPHER, kdf_iter=$KDF_ITER, cert=$CERT_PATH"

# === Step 2: Derive decryption passphrase from TLS certificate fingerprint ===
RAW_FP=$(openssl x509 -in "$CERT_PATH" -fingerprint -"$FP_HASH" -noout 2>/dev/null)
PASSPHRASE=$(echo "$RAW_FP" | cut -d= -f2 | tr -d ':' | tr 'A-F' 'a-f')

echo "Derived passphrase from certificate fingerprint"

# === Step 3: Decrypt the public key ===
openssl enc -d -"$ENC_CIPHER" -pbkdf2 -iter "$KDF_ITER" \
    -in "$PUBKEY_FILE" -out /app/public_key.txt \
    -pass "pass:$PASSPHRASE"

echo "Public key decrypted to /app/public_key.txt"

# === Step 4: Run the Kipnis-Shamir attack to forge the signature ===
python3 /solution/solve_vinaigrette.py
