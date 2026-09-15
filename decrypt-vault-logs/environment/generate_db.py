#!/usr/bin/env python3
"""
Generate all challenge artifacts during Docker build.

Creates:
  - /app/data/audit.db          Multi-engine encrypted audit log database
  - /app/keys/vault_priv.pem    RSA-2048 private key (encrypted PKCS#8)
  - /app/keys/vault_pub.pem     RSA-2048 public key
  - /app/keys/v1_wrapped.bin    v1 AES-128 key wrapped with RSA-OAEP
  - /app/config/deployment_manifest.json   Engine deployment timeline
  - /app/config/deployment_manifest.sig    Detached PKCS#1 v1.5 signature
"""

import json
import sqlite3
import struct
import hashlib
import os
import random

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import rsa, padding as asym_padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.padding import PKCS7

# ── Fixed parameters (NEVER exposed to the agent) ───────────────────

RNG = random.Random(42)

V1_KEY = bytes.fromhex('a1b2c3d4e5f6071829304050607080a1')       # AES-128
V2_KEY = bytes.fromhex(
    '4a7b3c9d1e2f5068a9b0c1d2e3f40516'
    '172839a0b1c2d3e4f5061728394a5b6c'
)                                                                  # AES-256
V3_KEY = bytes.fromhex(
    'f0e1d2c3b4a596877869504132231405'
    'f6e7d8c9b0a192837465544332211001'
)                                                                  # AES-256

RSA_PASSPHRASE = b'vault-hsm-export-2024'

SECRET_NAME = 'ROOT_API_TOKEN'
SECRET_VALUE = 'tk_9f84a2e7c3b1d0586742e9fa31bc7d2e'

# Engine deployment timeline
V1_START, V1_END = 1718000000, 1719500000
V2_START, V2_END = 1719500000, 1721000000
V3_START = 1721000000

DB_PATH = '/app/data/audit.db'

# ── Formatter helpers (mirror vault_logger/formatters.py) ────────────

USERS = ['admin', 'operator', 'svc_deploy', 'monitor', 'backup_agent']
ACTIONS = ['read', 'write', 'delete', 'rotate', 'execute']
RESOURCES = ['/vault/secrets', '/vault/keys', '/vault/config',
             '/vault/audit', '/vault/users']
ALERT_LEVELS = ['INFO', 'WARN', 'CRIT']
ALERT_MSGS = [
    'Routine integrity check passed',
    'Certificate renewal pending',
    'Disk utilization above 80 pct',
    'Backup completed successfully',
    'Service restart detected',
]


def _tag(body: str) -> str:
    return hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]


def fmt_heartbeat(sid, seq, ts):
    body = f"HEARTBEAT|OK|sid={sid:016x}|seq={seq:08x}|ts={ts}"
    return f"{body}|tag={_tag(body)}".encode()


def fmt_audit(user, action, resource, ts):
    body = f"AUDIT|user={user}|action={action}|resource={resource}|ts={ts}"
    return f"{body}|tag={_tag(body)}".encode()


def fmt_alert(level, msg, ts):
    body = f"ALERT|level={level}|msg={msg}|ts={ts}"
    return f"{body}|tag={_tag(body)}".encode()


def fmt_secret(name, value):
    body = f"SECRET|{name}={value}"
    return f"{body}|tag={_tag(body)}".encode()


def fmt_access(user, granted, resource, ts):
    status = "GRANTED" if granted else "DENIED"
    body = f"ACCESS|user={user}|status={status}|resource={resource}|ts={ts}"
    return f"{body}|tag={_tag(body)}".encode()


def random_entry(sid, seq, ts, rng):
    kind = rng.choice(['AUDIT', 'HEARTBEAT', 'ACCESS', 'ALERT'])
    if kind == 'HEARTBEAT':
        pt = fmt_heartbeat(sid, seq, ts)
    elif kind == 'AUDIT':
        pt = fmt_audit(rng.choice(USERS), rng.choice(ACTIONS),
                       rng.choice(RESOURCES), ts)
    elif kind == 'ACCESS':
        pt = fmt_access(rng.choice(USERS), rng.choice([True, False]),
                        rng.choice(RESOURCES), ts)
    else:
        pt = fmt_alert(rng.choice(ALERT_LEVELS), rng.choice(ALERT_MSGS), ts)
    return kind, pt


# ── Encryption helpers ───────────────────────────────────────────────

def encrypt_v1(plaintext):
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES128(V1_KEY), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(padded) + enc.finalize()


def encrypt_v2(session_id, counter, plaintext):
    nonce = struct.pack('<QQ', session_id, counter)
    cipher = Cipher(algorithms.AES256(V2_KEY), modes.CTR(nonce))
    enc = cipher.encryptor()
    return enc.update(plaintext) + enc.finalize()


def encrypt_v3(plaintext, aad=None):
    aesgcm = AESGCM(V3_KEY)
    nonce = RNG.randbytes(12)
    ct = aesgcm.encrypt(nonce, plaintext, aad)
    return nonce + ct


# ── RSA key generation and v1 key wrapping ───────────────────────────

def generate_keys():
    os.makedirs('/app/keys', exist_ok=True)

    rsa_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Encrypted PKCS#8 private key
    pem_priv = rsa_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(
            RSA_PASSPHRASE
        ),
    )
    with open('/app/keys/vault_priv.pem', 'wb') as f:
        f.write(pem_priv)

    # Public key
    pem_pub = rsa_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with open('/app/keys/vault_pub.pem', 'wb') as f:
        f.write(pem_pub)

    # Wrap v1 AES key with RSA-OAEP (SHA-256)
    wrapped = rsa_key.public_key().encrypt(
        V1_KEY,
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    with open('/app/keys/v1_wrapped.bin', 'wb') as f:
        f.write(wrapped)

    return rsa_key


# ── Signed deployment manifest ───────────────────────────────────────

def generate_manifest(rsa_key):
    os.makedirs('/app/config', exist_ok=True)

    manifest = {
        "vault_id": "prod-vault-01",
        "engine_transitions": [
            {
                "version": 1,
                "cipher_suite": "AES-128-ECB",
                "activated_at": V1_START,
                "deactivated_at": V1_END,
            },
            {
                "version": 2,
                "cipher_suite": "AES-256-CTR",
                "activated_at": V2_START,
                "deactivated_at": V2_END,
            },
            {
                "version": 3,
                "cipher_suite": "AES-256-GCM",
                "activated_at": V3_START,
                "deactivated_at": None,
            },
        ],
    }

    manifest_bytes = json.dumps(manifest, indent=2).encode('utf-8')
    with open('/app/config/deployment_manifest.json', 'wb') as f:
        f.write(manifest_bytes)

    # PKCS#1 v1.5 signature over the raw JSON bytes
    signature = rsa_key.sign(
        manifest_bytes,
        asym_padding.PKCS1v15(),
        hashes.SHA256(),
    )
    with open('/app/config/deployment_manifest.sig', 'wb') as f:
        f.write(signature)


# ── Database generation ──────────────────────────────────────────────

def generate_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    conn.execute('''CREATE TABLE IF NOT EXISTS log_entries (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id      INTEGER NOT NULL,
        entry_seq       INTEGER NOT NULL,
        entry_type      TEXT    NOT NULL,
        engine_version  INTEGER NOT NULL,
        ciphertext      BLOB   NOT NULL,
        created_at      INTEGER NOT NULL
    )''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_session_seq
                    ON log_entries(session_id, entry_seq)''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_engine
                    ON log_entries(engine_version)''')

    rng = RNG

    # ── v1 sessions (AES-128-ECB) ────────────────────────────────────
    for i in range(6):
        sid = V1_START + i * 200000 + rng.randint(0, 50000)
        n_entries = rng.randint(15, 25)
        for seq in range(n_entries):
            ts = sid + seq * 30 + rng.randint(0, 15)
            entry_type, pt = random_entry(sid, seq, ts, rng)
            ct = encrypt_v1(pt)
            conn.execute(
                'INSERT INTO log_entries '
                '(session_id, entry_seq, entry_type, engine_version, '
                'ciphertext, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                (sid, seq, entry_type, 1, ct, ts),
            )

    # ── v2 sessions (AES-256-CTR) ────────────────────────────────────
    v2_sessions = []
    for i in range(12):
        sid = V2_START + i * 100000 + rng.randint(0, 50000)
        v2_sessions.append(sid)

    # Two sessions that COLLIDE on session_id → nonce reuse
    collision_sid = V2_START + 750000
    v2_sessions.append(collision_sid)
    v2_sessions.append(collision_sid)
    rng.shuffle(v2_sessions)

    col_indices = [i for i, s in enumerate(v2_sessions)
                   if s == collision_sid]
    col_a, col_b = col_indices[0], col_indices[1]

    for sess_idx, sid in enumerate(v2_sessions):
        n_entries = rng.randint(18, 35)
        is_a = (sess_idx == col_a)
        is_b = (sess_idx == col_b)

        for seq in range(n_entries):
            ts = sid + seq * 30 + rng.randint(0, 15)

            if is_a and seq == 5:
                entry_type = 'HEARTBEAT'
                pt = fmt_heartbeat(sid, seq, ts)
            elif is_b and seq == 5:
                entry_type = 'SECRET'
                pt = fmt_secret(SECRET_NAME, SECRET_VALUE)
            else:
                entry_type, pt = random_entry(sid, seq, ts, rng)

            ct = encrypt_v2(sid, seq, pt)
            conn.execute(
                'INSERT INTO log_entries '
                '(session_id, entry_seq, entry_type, engine_version, '
                'ciphertext, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                (sid, seq, entry_type, 2, ct, ts),
            )

    # ── v3 sessions (AES-256-GCM) ────────────────────────────────────
    for i in range(6):
        sid = V3_START + i * 200000 + rng.randint(0, 50000)
        n_entries = rng.randint(15, 25)
        for seq in range(n_entries):
            ts = sid + seq * 30 + rng.randint(0, 15)
            entry_type, pt = random_entry(sid, seq, ts, rng)
            aad = f"{sid}:{seq}".encode()
            ct = encrypt_v3(pt, aad)
            conn.execute(
                'INSERT INTO log_entries '
                '(session_id, entry_seq, entry_type, engine_version, '
                'ciphertext, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                (sid, seq, entry_type, 3, ct, ts),
            )

    conn.commit()
    conn.close()
    print(f"[+] Generated {DB_PATH}")
    print(f"[+] Collision at session_id={collision_sid}, entry_seq=5")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    rsa_key = generate_keys()
    print("[+] RSA keys and wrapped v1 key generated")
    generate_manifest(rsa_key)
    print("[+] Signed deployment manifest generated")
    generate_db()
    print("[+] All artifacts generated successfully")


if __name__ == '__main__':
    main()
