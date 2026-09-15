#!/usr/bin/env python3
"""Generate DSA signature forensics challenge data in crypto-native formats.
Deleted after execution during Docker build - do not leave accessible."""

import base64
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone


# Standard DSA parameters (512-bit p, 160-bit q) from FIPS 186
p = 0x8df2a494492276aa3d25759bb06869cbeac0d83afb8d0cf7cbb8324f0d7882e5d0762fc5b7210eafc2e9adac32ab7aac49693dfbf83724c2ec0736ee31c80291
q = 0xc773218c737ec8ee993b4f2ded30f48edace915f
g = 0x626d027839ea0a13413163a55b4cb500299d5522956cefcb3bff10f399ce2c2e71cb9de5fa24babf58e5b79521925c9cc42e9f6f464b088cc572af53e6d78802


# === DER/ASN.1 encoding helpers ===

def der_length(length):
    if length < 0x80:
        return bytes([length])
    elif length < 0x100:
        return b'\x81' + bytes([length])
    else:
        return b'\x82' + length.to_bytes(2, 'big')


def der_integer(value):
    if value == 0:
        return b'\x02\x01\x00'
    byte_len = (value.bit_length() + 7) // 8
    raw = value.to_bytes(byte_len, 'big')
    if raw[0] & 0x80:
        raw = b'\x00' + raw
    return b'\x02' + der_length(len(raw)) + raw


def der_sequence(contents):
    return b'\x30' + der_length(len(contents)) + contents


def der_bitstring(contents):
    payload = b'\x00' + contents
    return b'\x03' + der_length(len(payload)) + payload


def der_oid_dsa():
    """OID 1.2.840.10040.4.1 (id-dsa)"""
    oid_bytes = bytes([0x2A, 0x86, 0x48, 0xCE, 0x38, 0x04, 0x01])
    return b'\x06' + der_length(len(oid_bytes)) + oid_bytes


def make_pem(der_bytes, label):
    b64 = base64.b64encode(der_bytes).decode('ascii')
    lines = [b64[i:i+64] for i in range(0, len(b64), 64)]
    return f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n"


def make_dsa_params_pem():
    inner = der_integer(p) + der_integer(q) + der_integer(g)
    return make_pem(der_sequence(inner), "DSA PARAMETERS")


def make_dsa_pubkey_pem(y_val):
    """Create SubjectPublicKeyInfo PEM for a DSA public key (RFC 3279)."""
    # DSS-Params
    params_seq = der_sequence(der_integer(p) + der_integer(q) + der_integer(g))
    # AlgorithmIdentifier
    algo_seq = der_sequence(der_oid_dsa() + params_seq)
    # subjectPublicKey: BIT STRING containing DER-encoded INTEGER y
    pubkey_bits = der_bitstring(der_integer(y_val))
    # SubjectPublicKeyInfo
    return make_pem(der_sequence(algo_seq + pubkey_bits), "PUBLIC KEY")


def make_dsa_privkey_pem(x_val, y_val):
    """Create traditional OpenSSL DSA private key PEM."""
    inner = (der_integer(0) + der_integer(p) + der_integer(q) +
             der_integer(g) + der_integer(y_val) + der_integer(x_val))
    return make_pem(der_sequence(inner), "DSA PRIVATE KEY")


def make_sig_der(r_val, s_val):
    """Create DER-encoded DSA-Sig-Value: SEQUENCE { INTEGER r, INTEGER s }."""
    return der_sequence(der_integer(r_val) + der_integer(s_val))


# === DER parsing (for self-check) ===

def parse_der_length(data, offset):
    if data[offset] < 0x80:
        return data[offset], offset + 1
    num_bytes = data[offset] & 0x7f
    offset += 1
    length = int.from_bytes(data[offset:offset + num_bytes], 'big')
    return length, offset + num_bytes


def parse_der_integer(data, offset):
    assert data[offset] == 0x02
    offset += 1
    length, offset = parse_der_length(data, offset)
    value = int.from_bytes(data[offset:offset + length], 'big')
    return value, offset + length


def parse_sig_der(data):
    assert data[0] == 0x30
    _, offset = parse_der_length(data, 1)
    r, offset = parse_der_integer(data, offset)
    s, offset = parse_der_integer(data, offset)
    return r, s


# === Crypto utilities ===

def det_int(seed_str, modulus):
    h = hashlib.sha512(seed_str.encode()).digest()
    return int.from_bytes(h, 'big') % (modulus - 2) + 2


def modinv(a, m):
    a = a % m
    g_val, x = m, 0
    b, y = a, 1
    while b > 0:
        quo = g_val // b
        g_val, b = b, g_val - quo * b
        x, y = y, x - quo * y
    if g_val != 1:
        raise ValueError("No modular inverse")
    return x % m


def sha1_int(msg):
    return int(hashlib.sha1(msg.encode('utf-8')).hexdigest(), 16)


def dsa_sign(msg, x_val, k_val):
    h = sha1_int(msg)
    r = pow(g, k_val, p) % q
    s = (modinv(k_val, q) * (h + x_val * r)) % q
    return h, r, s


def dsa_verify(h, r, s, y_val):
    if not (0 < r < q and 0 < s < q):
        return False
    w = modinv(s, q)
    u1 = (h * w) % q
    u2 = (r * w) % q
    v = (pow(g, u1, p) * pow(y_val, u2, p)) % p % q
    return v == r


# === Generate key pairs (deterministic) ===

keys = {}
for kid in ["alpha", "beta", "gamma"]:
    x_val = det_int(f"dsa_forensics_key_{kid}_private_2024", q)
    y_val = pow(g, x_val, p)
    keys[kid] = {"x": x_val, "y": y_val}

# === Define messages ===

messages = {
    "alpha": [
        "firmware_update_v3.2.1_sha256:a1b2c3d4",
        "config_push_node_cluster_east_prod",
        "certificate_renewal_wildcard_2024q2",
        "security_patch_cve_2024_31497_apply",
        "audit_log_rotation_compliance_soc2"
    ],
    "beta": [
        "database_migration_schema_v47_rollout",
        "load_balancer_weight_adjustment_us_west",
        "dns_zone_transfer_primary_to_secondary",
        "firewall_acl_update_port_8443_ingress",
        "service_mesh_istio_sidecar_injection"
    ],
    "gamma": [
        "deployment_canary_release_api_v2.1",
        "incident_response_runbook_execution_ir42",
        "backup_verification_quarterly_dr_test",
        "user_provisioning_ldap_sync_batch_2847",
        "api_gateway_rate_limit_policy_update"
    ]
}

# === Generate nonces with vulnerability patterns ===

# Alpha: indices 0 and 3 share the SAME nonce (nonce reuse)
k_shared_alpha = det_int("nonce_alpha_shared_forensics_2024", q)
nonces_alpha = [
    k_shared_alpha,
    det_int("nonce_alpha_1_forensics_2024", q),
    det_int("nonce_alpha_2_forensics_2024", q),
    k_shared_alpha,
    det_int("nonce_alpha_4_forensics_2024", q)
]

# Beta: indices 1 and 4 share the SAME nonce (nonce reuse)
k_shared_beta = det_int("nonce_beta_shared_forensics_2024", q)
nonces_beta = [
    det_int("nonce_beta_0_forensics_2024", q),
    k_shared_beta,
    det_int("nonce_beta_2_forensics_2024", q),
    det_int("nonce_beta_3_forensics_2024", q),
    k_shared_beta
]

# Gamma: indices 2 and 3 use SEQUENTIAL nonces (k, k+1)
k_seq = det_int("nonce_gamma_seq_forensics_2024", q - 1)
nonces_gamma = [
    det_int("nonce_gamma_0_forensics_2024", q),
    det_int("nonce_gamma_1_forensics_2024", q),
    k_seq,
    k_seq + 1,
    det_int("nonce_gamma_4_forensics_2024", q)
]

nonces = {"alpha": nonces_alpha, "beta": nonces_beta, "gamma": nonces_gamma}


# === Create directory structure ===

os.makedirs("/app/data/keys", exist_ok=True)
os.makedirs("/app/results", exist_ok=True)


# === Write DSA parameters PEM ===

with open("/app/data/params.pem", "w") as f:
    f.write(make_dsa_params_pem())


# === Write public key PEM files ===

for kid in ["alpha", "beta", "gamma"]:
    with open(f"/app/data/keys/{kid}.pub.pem", "w") as f:
        f.write(make_dsa_pubkey_pem(keys[kid]["y"]))


# === Sign all messages ===

all_records = []
for kid in ["alpha", "beta", "gamma"]:
    for i, msg in enumerate(messages[kid]):
        h, r, s = dsa_sign(msg, keys[kid]["x"], nonces[kid][i])
        assert dsa_verify(h, r, s, keys[kid]["y"]), f"Self-verify failed: {kid}:{i}"
        all_records.append((msg, h, r, s, kid))

# Deterministic shuffle by MD5 of message
all_records.sort(key=lambda rec: hashlib.md5(rec[0].encode()).hexdigest())


# === Store signatures in SQLite database ===

db_path = "/app/data/audit.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    message TEXT NOT NULL,
    signature_der BLOB NOT NULL
)
""")

base_ts = 1706745600  # 2024-02-01 00:00:00 UTC

for idx, (msg, h, r, s, kid_actual) in enumerate(all_records):
    sig_der = make_sig_der(r, s)
    ts = base_ts + idx * 3600 + det_int(f"ts_jitter_{idx}", 1800)
    ts_str = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    cursor.execute(
        "INSERT INTO audit_log (timestamp, message, signature_der) VALUES (?, ?, ?)",
        (ts_str, msg, sig_der)
    )

conn.commit()
conn.close()


# === Write challenge messages ===

challenges = [
    {"challenge_id": 0, "message": "emergency_key_rotation_all_services_2024", "target_key": "alpha"},
    {"challenge_id": 1, "message": "production_database_failover_initiated", "target_key": "beta"},
    {"challenge_id": 2, "message": "zero_day_patch_deployment_critical_infra", "target_key": "gamma"}
]

with open("/app/data/challenges.json", "w") as f:
    json.dump(challenges, f, indent=2)


# === Sanity checks ===

# Verify signature DER round-trip through SQLite
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT message, signature_der FROM audit_log")
rows = cursor.fetchall()
conn.close()

assert len(rows) == 15, f"Expected 15 records, got {len(rows)}"

for msg, sig_blob in rows:
    r_check, s_check = parse_sig_der(sig_blob)
    h_check = sha1_int(msg)
    verified = False
    for kid in ["alpha", "beta", "gamma"]:
        if dsa_verify(h_check, r_check, s_check, keys[kid]["y"]):
            verified = True
            break
    assert verified, f"DER round-trip verification failed for: {msg}"

# Verify nonce-reuse r-value counts
alpha_rs = []
beta_rs = []
gamma_rs = []
for msg, sig_blob in rows:
    r_check, _ = parse_sig_der(sig_blob)
    h_check = sha1_int(msg)
    for kid, kid_list in [("alpha", alpha_rs), ("beta", beta_rs), ("gamma", gamma_rs)]:
        if dsa_verify(h_check, r_check, _, keys[kid]["y"]):
            kid_list.append(r_check)
            break

assert len(set(alpha_rs)) == 4, f"Alpha should have 4 unique r values"
assert len(set(beta_rs)) == 4, f"Beta should have 4 unique r values"
assert len(set(gamma_rs)) == 5, f"Gamma should have ALL unique r values"

# Verify key pairs
for kid in keys:
    assert pow(g, keys[kid]["x"], p) == keys[kid]["y"]

print("Challenge data generated and verified successfully.")
print(f"  DSA parameters: /app/data/params.pem")
print(f"  Public keys: /app/data/keys/{{alpha,beta,gamma}}.pub.pem")
print(f"  Audit log: /app/data/audit.db (15 DER-encoded signatures)")
print(f"  Challenges: /app/data/challenges.json (3 messages)")
