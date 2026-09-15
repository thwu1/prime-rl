"""
Build the tkdb database: create schema, derive keys, populate organizations.

"""

import os
import sqlite3

from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def main():
    # --- Load CA private key ---
    with open("/app/pki/ca.key", "rb") as f:
        ca_key = serialization.load_pem_private_key(f.read(), password=None)
    ca_bytes = ca_key.private_numbers().private_value.to_bytes(32, "big")

    # --- Derive master key ---
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32,
                 salt=b"tkdb-salt-2026", info=b"tkdb-master-key-v1")
    master_key = hkdf.derive(ca_bytes)

    # --- Create database ---
    db_path = "/app/tkdb.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE TABLE organizations (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            encrypted_root_key BLOB NOT NULL,
            nonce BLOB NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE blacklist (
            nonce TEXT NOT NULL UNIQUE,
            required_until TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation TEXT NOT NULL,
            token_identifier TEXT NOT NULL,
            org_id INTEGER,
            result TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --- Populate organizations ---
    orgs = [
        (1, "flyio-prod"),
        (2, "flyio-staging"),
        (3, "customer-acme"),
    ]

    for org_id, org_name in orgs:
        # Derive per-org root key
        hkdf_org = HKDF(algorithm=hashes.SHA256(), length=32,
                         salt=b"tkdb-salt-2026",
                         info=f"org-root-key-{org_id}".encode())
        root_key = hkdf_org.derive(master_key)

        # Encrypt root key with AES-256-GCM
        nonce = os.urandom(12)
        aesgcm = AESGCM(master_key)
        encrypted_root_key = aesgcm.encrypt(nonce, root_key, None)

        conn.execute(
            "INSERT INTO organizations (id, name, encrypted_root_key, nonce) "
            "VALUES (?, ?, ?, ?)",
            (org_id, org_name, encrypted_root_key, nonce))

    conn.commit()
    conn.close()
    print("Database created at", db_path)


if __name__ == "__main__":
    main()
