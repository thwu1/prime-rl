#!/usr/bin/env python3
"""
Solve the vault encryption engine audit & remediation challenge.

Strategy
--------
1. Verify the deployment manifest signature.
2. Unwrap the v1 AES-128 key via RSA-OAEP.
3. Exploit v2 CTR nonce reuse to recover the API token.
4. Compute quantitative risk metrics for each engine.
5. Design and create a secure remediation engine (HKDF + AES-256-GCM).
6. Create and execute a migration tool to re-encrypt all v1 data.
7. Produce the audit report and solution file.

"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys

DB_PATH = '/app/data/audit.db'
OUTPUT = '/app/solution.txt'
REPORT = '/app/audit_report.json'
REMEDIATION_DIR = '/app/remediation'


# ── Step 1: Verify deployment manifest ───────────────────────────────

def verify_manifest():
    result = subprocess.run([
        'openssl', 'dgst', '-sha256',
        '-verify', '/app/keys/vault_pub.pem',
        '-signature', '/app/config/deployment_manifest.sig',
        '/app/config/deployment_manifest.json',
    ], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"WARNING: Manifest verification failed: {result.stderr}",
              file=sys.stderr)
    else:
        print(f"Manifest signature: {result.stdout.strip()}")
    with open('/app/config/deployment_manifest.json') as f:
        return json.load(f)


# ── Step 2: Unwrap v1 AES key ────────────────────────────────────────

def unwrap_v1_key():
    result = subprocess.run([
        'openssl', 'pkeyutl', '-decrypt',
        '-inkey', '/app/keys/vault_priv.pem',
        '-passin', 'pass:vault-hsm-export-2024',
        '-pkeyopt', 'rsa_padding_mode:oaep',
        '-pkeyopt', 'rsa_oaep_md:sha256',
        '-pkeyopt', 'rsa_mgf1_md:sha256',
        '-in', '/app/keys/v1_wrapped.bin',
        '-out', '/tmp/v1_key.bin',
    ], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"WARNING: v1 key unwrap failed: {result.stderr}",
              file=sys.stderr)
        return None
    with open('/tmp/v1_key.bin', 'rb') as f:
        key = f.read()
    print(f"v1 AES key recovered ({len(key)} bytes): {key.hex()}")
    return key


# ── Step 3: Exploit v2 CTR nonce reuse ───────────────────────────────

def _integrity_tag(body: str) -> str:
    return hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]


def format_heartbeat(session_id: int, entry_seq: int, ts: int) -> bytes:
    body = (f"HEARTBEAT|OK|sid={session_id:016x}"
            f"|seq={entry_seq:08x}|ts={ts}")
    tag = _integrity_tag(body)
    return f"{body}|tag={tag}".encode('utf-8')


def exploit_v2_collision(conn):
    cur = conn.cursor()
    cur.execute('''
        SELECT a.session_id,  a.entry_seq,
               a.ciphertext,  a.created_at,
               b.ciphertext
        FROM   log_entries a
        JOIN   log_entries b
          ON   a.session_id = b.session_id
         AND   a.entry_seq  = b.entry_seq
         AND   a.id != b.id
        WHERE  a.entry_type = 'HEARTBEAT'
          AND  b.entry_type = 'SECRET'
          AND  a.engine_version = 2
          AND  b.engine_version = 2
    ''')
    rows = cur.fetchall()
    if not rows:
        print("ERROR: no HEARTBEAT/SECRET nonce collision found",
              file=sys.stderr)
        return None

    for session_id, entry_seq, hb_ct, hb_ts, secret_ct in rows:
        hb_plain = format_heartbeat(session_id, entry_seq, hb_ts)
        keystream = bytes(a ^ b for a, b in zip(hb_ct, hb_plain))
        secret_plain = bytes(a ^ b for a, b in zip(secret_ct, keystream))
        decoded = secret_plain.decode('utf-8', errors='replace')
        print(f"\nDecrypted v2 entry: {decoded}")
        parts = decoded.split('|')
        if parts[0] != 'SECRET':
            continue
        _name, value = parts[1].split('=', 1)
        return value
    return None


# ── Step 4: Quantitative risk analysis ───────────────────────────────

def count_v2_at_risk(conn):
    """Count v2 entries recoverable via nonce-collision with known plaintext."""
    cur = conn.cursor()
    cur.execute('''
        SELECT COUNT(DISTINCT b.id)
        FROM   log_entries a
        JOIN   log_entries b
          ON   a.session_id = b.session_id
         AND   a.entry_seq  = b.entry_seq
         AND   a.id != b.id
        WHERE  a.engine_version = 2
          AND  b.engine_version = 2
          AND  a.entry_type = 'HEARTBEAT'
    ''')
    return cur.fetchone()[0]


def compute_v2_collision_prob(conn):
    """Birthday-style probability of session_id collision in v2."""
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(DISTINCT session_id) "
        "FROM log_entries WHERE engine_version = 2"
    )
    n_sessions = cur.fetchone()[0]
    deployment_window = 1_500_000  # seconds
    pairs = n_sessions * (n_sessions - 1) // 2
    prob = 1.0 - (1.0 - 1.0 / deployment_window) ** pairs
    return prob


# ── Step 5: Create remediation files ─────────────────────────────────

def create_remediation_files():
    """Copy the engine and migration templates into /app/remediation/."""
    os.makedirs(REMEDIATION_DIR, exist_ok=True)

    # Copy engine
    shutil.copy2('/solution/engine_template.py',
                 os.path.join(REMEDIATION_DIR, 'secure_engine.py'))
    print(f"Created {REMEDIATION_DIR}/secure_engine.py")

    # Copy migration script
    migrate_dst = os.path.join(REMEDIATION_DIR, 'migrate.py')
    shutil.copy2('/solution/migrate_template.py', migrate_dst)
    os.chmod(migrate_dst, 0o755)
    print(f"Created {migrate_dst}")


def run_migration():
    """Generate migration key and execute the migration script."""
    key_path = os.path.join(REMEDIATION_DIR, 'migration_key.bin')
    master_key = os.urandom(32)
    with open(key_path, 'wb') as f:
        f.write(master_key)
    print(f"Generated 32-byte migration key at {key_path}")

    result = subprocess.run(
        [sys.executable, os.path.join(REMEDIATION_DIR, 'migrate.py')],
        capture_output=True, text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"Migration failed: {result.stderr}", file=sys.stderr)
        return False
    return True


# ── Step 6: Write deliverables ───────────────────────────────────────

def write_report(token, conn):
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM log_entries WHERE engine_version = 1")
    v1_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM log_entries WHERE engine_version = 3")
    v3_count = cur.fetchone()[0]

    v2_at_risk = count_v2_at_risk(conn)
    v2_collision_prob = compute_v2_collision_prob(conn)

    # v3 birthday bound: P ~ n^2 / (2 * 2^96)
    v3_collision_prob = (v3_count ** 2) / (2.0 * (2 ** 96))

    report = {
        "engines": [
            {
                "version": 1,
                "cipher_suite": "AES-128-ECB",
                "vulnerability_class": "CRITICAL",
                "weakness_description": (
                    "ECB mode is deterministic: identical plaintext blocks "
                    "always produce identical ciphertext, enabling frequency "
                    "analysis and pattern detection. The AES-128 key was "
                    "recovered from an RSA-OAEP wrapped export, allowing "
                    "full decryption of all v1 entries."
                ),
                "collision_probability": 1.0,
                "data_at_risk_count": v1_count,
            },
            {
                "version": 2,
                "cipher_suite": "AES-256-CTR",
                "vulnerability_class": "HIGH",
                "weakness_description": (
                    "CTR nonce is deterministically derived from session_id "
                    "(epoch second at daemon start) and entry sequence. When "
                    "two daemon processes start within the same calendar "
                    "second they share a session_id, causing complete nonce "
                    "reuse. This enables XOR-based keystream recovery via "
                    "known-plaintext (HEARTBEAT) entries."
                ),
                "collision_probability": v2_collision_prob,
                "data_at_risk_count": v2_at_risk,
            },
            {
                "version": 3,
                "cipher_suite": "AES-256-GCM",
                "vulnerability_class": "NONE",
                "weakness_description": (
                    "GCM with cryptographically random 12-byte nonces "
                    "provides authenticated encryption. Birthday-bound "
                    "collision probability is negligible at the observed "
                    "entry volume. No structural weaknesses identified."
                ),
                "collision_probability": v3_collision_prob,
                "data_at_risk_count": 0,
            },
        ],
        "recovered_secrets": [token],
        "recommended_engine": 3,
    }

    with open(REPORT, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"Audit report written to {REPORT}")


# ── Main ─────────────────────────────────────────────────────────────

def solve():
    # Verify and read deployment manifest
    manifest = verify_manifest()
    for t in manifest['engine_transitions']:
        print(f"  v{t['version']} ({t['cipher_suite']}): "
              f"{t['activated_at']} -> {t['deactivated_at']}")

    # Unwrap v1 key
    v1_key = unwrap_v1_key()

    # Open database
    conn = sqlite3.connect(DB_PATH)

    # Exploit v2 nonce reuse to recover the API token
    token = exploit_v2_collision(conn)
    if not token:
        print("FATAL: could not recover token", file=sys.stderr)
        sys.exit(1)

    # Write solution
    with open(OUTPUT, 'w') as f:
        f.write(token)
    print(f"Token written to {OUTPUT}")

    # Create remediation engine and migration script
    create_remediation_files()

    # Execute migration
    if not run_migration():
        print("FATAL: migration failed", file=sys.stderr)
        sys.exit(1)

    # Write quantitative audit report
    write_report(token, conn)
    conn.close()


if __name__ == '__main__':
    solve()
