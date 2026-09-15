# Token Verification Service (tkdb) — Architecture Specification

## Overview

Build a token verification service (`tkdb`) that manages macaroon token lifecycle:
issuing, verifying, revoking, and deriving service tokens. The service stores
per-organization HMAC root keys encrypted in a SQLite database, with key material
derived from a PKI infrastructure via HKDF.

A working macaroon library is provided at `/app/macaroon/__init__.py`.

## 1. PKI Requirements

Generate certificates using the `openssl` CLI with ECDSA P-256 (prime256v1):

| File | Description |
|------|-------------|
| `/app/pki/ca.key` | EC P-256 private key for the CA |
| `/app/pki/ca.crt` | Self-signed CA certificate, CN=`tkdb-ca`, validity 3650 days, SHA-256 |
| `/app/pki/server.key` | EC P-256 private key for the server |
| `/app/pki/server.crt` | Server certificate signed by the CA, CN=`tkdb-server`, validity 365 days |

The CA certificate must be verifiable: `openssl verify -CAfile ca.crt server.crt` must succeed.

## 2. Key Derivation

All key derivation uses HKDF-SHA256 (from `cryptography.hazmat.primitives.kdf.hkdf`).

### Master Key

Derived from the CA private key's raw scalar (big-endian, 32 bytes):

```
IKM  = ca_private_key.private_numbers().private_value.to_bytes(32, "big")
salt = b"tkdb-salt-2026"
info = b"tkdb-master-key-v1"
master_key = HKDF-SHA256(IKM, salt, info, length=32)
```

### Per-Organization Root Keys

Each organization gets a 32-byte root key derived from the master key:

```
IKM  = master_key
salt = b"tkdb-salt-2026"
info = f"org-root-key-{org_id}".encode()
root_key = HKDF-SHA256(IKM, salt, info, length=32)
```

### Storage Encryption

Root keys are stored AES-256-GCM encrypted using the master key:

```
nonce = os.urandom(12)
encrypted_root_key = AES-256-GCM(master_key, nonce).encrypt(root_key)
```

Both `encrypted_root_key` and `nonce` are stored as BLOBs in the database.

## 3. Database Schema

SQLite database at `/app/tkdb.db`.

### Table: organizations

```sql
CREATE TABLE organizations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    encrypted_root_key BLOB NOT NULL,
    nonce BLOB NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### Table: blacklist

```sql
CREATE TABLE blacklist (
    nonce TEXT NOT NULL UNIQUE,
    required_until TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### Table: audit_log

```sql
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL,
    token_identifier TEXT NOT NULL,
    org_id INTEGER,
    result TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### Initial Data

Populate three organizations:

| id | name |
|----|------|
| 1 | flyio-prod |
| 2 | flyio-staging |
| 3 | customer-acme |

## 4. Service Module

Implement a Python module at `/app/tkdb/service.py` exporting a class `TkdbService`.

### Constructor

```python
TkdbService(db_path: str, pki_dir: str)
```

Loads PKI material, derives the master key, connects to the database.

### issue(org_name, caveats=None) → dict

Issue a macaroon for the given organization.

- Look up the org's encrypted root key and decrypt it.
- Create a `Macaroon` with `location="https://tkdb.internal"` and identifier
  format `"org:{org_id}:{random_hex_16}"` where `random_hex_16` is 16 random
  bytes hex-encoded.
- Add any first-party caveats from the list.
- Log to `audit_log` with `operation="issue"`.
- Return `{"token": base64_encoded_serialized_macaroon, "identifier": identifier}`.

### verify(token_b64, satisfiers=None) → dict

Verify a macaroon token with cache-consistent revocation.

- Decode and deserialize the token.
- Parse `org_id` from the identifier.
- Implement cache-consistent revocation per the selected design from
  `/app/DESIGN_CANDIDATES.md` (see Section 6).
- If cache miss, perform full verification using the library's `Verifier`.
  Apply `satisfiers` as exact satisfiers if provided.
- Log to `audit_log` with `operation="verify"`.
- Return `{"valid": bool, "identifier": str, "cached": bool}`.

### revoke(identifier) → dict

Revoke a token by identifier.

- Insert into `blacklist` table.
- Log to `audit_log` with `operation="revoke"`.
- Return `{"revoked": True, "identifier": identifier}`.

### derive_service_token(token_b64, strip_predicates=None) → dict

Derive a service token from a user token.

- Deserialize and verify the original token (use a permissive verifier that
  accepts all first-party caveats).
- Create a new macaroon with identifier format `"svc:{org_id}:{random_hex_16}"`.
- Re-add first-party caveats except those matching `strip_predicates` prefixes.
- Skip all third-party caveats.
- Log to `audit_log` with `operation="derive"`.
- Return `{"token": base64_encoded, "identifier": new_identifier}`.

### get_revocations(since=None) → list

Return recent revocations from the `blacklist` table.
Each entry: `{"identifier": str, "revoked_at": str}`.

### cache_stats() → dict

Return `{"size": int, "hits": int, "misses": int}`.

## 5. Evaluation

Analyze the three candidate cache-invalidation designs in `/app/DESIGN_CANDIDATES.md`.
Write your security evaluation to `/app/EVALUATION.md`, selecting the correct design
and explaining why the others fail.

## 6. Cache-Consistent Revocation

The verification cache stores results keyed by token signature. The critical
requirement: **a revoked token must never be returned as valid from cache**.
See `/app/DESIGN_CANDIDATES.md` for three candidate approaches. Your implementation
must use the correct one.
