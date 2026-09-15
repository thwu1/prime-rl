# Token Verification Service (tkdb) — System Requirements


## 1. Overview

The tkdb service manages macaroon-based authorization tokens for a multi-tenant
platform. It provides token issuance, verification with caching, revocation,
and service token derivation. Organization-specific HMAC root keys are derived
from PKI infrastructure and stored encrypted in SQLite.

A working macaroon library is available at `/app/macaroon/__init__.py`.

A draft implementation exists at `/app/tkdb/draft_service.py`. It is
functionally incomplete and has not passed security review.

## 2. PKI Infrastructure

| Artifact | Path | Algorithm | Subject CN | Validity | Signed By |
|----------|------|-----------|-----------|----------|-----------|
| CA Key | `/app/pki/ca.key` | ECDSA P-256 | — | — | — |
| CA Certificate | `/app/pki/ca.crt` | ECDSA P-256 | `tkdb-ca` | 3650 days | Self |
| Server Key | `/app/pki/server.key` | ECDSA P-256 | — | — | — |
| Server Certificate | `/app/pki/server.crt` | ECDSA P-256 | `tkdb-server` | 365 days | CA |

Constraint: `openssl verify -CAfile /app/pki/ca.crt /app/pki/server.crt` must
return OK.

## 3. Key Management

### 3.1 Derivation

All key derivation uses HKDF-SHA256 with 32-byte output length.

| Key | IKM | Salt | Info |
|-----|-----|------|------|
| Master | CA private key scalar (32 bytes, big-endian) | `tkdb-salt-2026` | `tkdb-master-key-v1` |
| Per-org root (id=N) | Master key | `tkdb-salt-2026` | `org-root-key-{N}` |

### 3.2 At-Rest Encryption

Organization root keys are stored encrypted using AES-256-GCM with the master
key as the encryption key. Each encrypted key uses a unique random 12-byte
nonce. The database stores both the ciphertext (`encrypted_root_key` BLOB) and
the nonce (`nonce` BLOB).

## 4. Database

SQLite database at `/app/tkdb.db`.

### Tables

**organizations** — `id` INTEGER PRIMARY KEY, `name` TEXT NOT NULL UNIQUE,
`encrypted_root_key` BLOB NOT NULL, `nonce` BLOB NOT NULL,
`created_at` TEXT DEFAULT CURRENT_TIMESTAMP

**blacklist** — `nonce` TEXT NOT NULL UNIQUE, `required_until` TEXT,
`created_at` TEXT DEFAULT CURRENT_TIMESTAMP

**audit_log** — `id` INTEGER PRIMARY KEY AUTOINCREMENT, `operation` TEXT NOT NULL,
`token_identifier` TEXT NOT NULL, `org_id` INTEGER, `result` TEXT,
`created_at` TEXT DEFAULT CURRENT_TIMESTAMP

### Initial Organizations

| id | name |
|----|------|
| 1  | flyio-prod |
| 2  | flyio-staging |
| 3  | customer-acme |

## 5. Service API

Module path: `/app/tkdb/service.py`
Class: `TkdbService(db_path: str, pki_dir: str)`

### Methods

**issue(org_name, caveats=None) → dict**
Issue a macaroon for the named organization. Token location:
`https://tkdb.internal`. Identifier format: `org:{org_id}:{hex(16 random bytes)}`.
Attach first-party caveats if provided.
Returns `{"token": <base64>, "identifier": <str>}`.

**verify(token_b64, satisfiers=None) → dict**
Verify a token with caching. Apply satisfiers as exact predicates.
Returns `{"valid": <bool>, "identifier": <str>, "cached": <bool>}`.

**revoke(identifier) → dict**
Revoke a token via the blacklist.
Returns `{"revoked": True, "identifier": <str>}`.

**derive_service_token(token_b64, strip_predicates=None) → dict**
Derive a restricted service token from a verified user token. New identifier
format: `svc:{org_id}:{hex(16 random bytes)}`. Preserve first-party caveats
except those whose predicates start with any entry in `strip_predicates`. Skip
third-party caveats.
Returns `{"token": <base64>, "identifier": <str>}`.

**get_revocations(since=None) → list**
Return revocation entries from the blacklist.
Each entry: `{"identifier": <str>, "revoked_at": <str>}`.

**cache_stats() → dict**
Return `{"size": <int>, "hits": <int>, "misses": <int>}`.

## 6. Security Properties

| ID | Property |
|----|----------|
| SP-1 | A revoked token must **never** be returned as valid from the verification cache |
| SP-2 | No TOCTOU race conditions between concurrent `revoke()` and `verify()` operations |
| SP-3 | Organization root keys must not be stored or transmitted in plaintext |
| SP-4 | All token lifecycle operations (issue, verify, revoke, derive) must be recorded in the audit log |
| SP-5 | Key derivation must be deterministic and reproducible from the CA private key alone |

## 7. Evaluation Deliverable

Analyze the three cache-invalidation design candidates in
`/app/DESIGN_CANDIDATES.md` against properties SP-1 and SP-2. Document your
analysis at `/app/EVALUATION.md`, identifying the correct design and the
security weaknesses of the rejected candidates.
