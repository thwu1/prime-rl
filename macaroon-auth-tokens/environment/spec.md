# Macaroon Authorization Token System — Specification

## Overview

Implement a Macaroon authorization token library as a Python package at `/app/macaroon/`.
All public classes must be importable from the package root:
```python
from macaroon import Macaroon, Verifier, ThirdPartyDischarger, RevocationStore, CachingVerifier, TokenService
```

Dependencies available at runtime: `cryptography`, `msgpack` (install in your code or assume present).

---

## 1. Cryptographic Primitives

- **HMAC**: HMAC-SHA256 from Python `hmac` + `hashlib.sha256`. Output: 32 bytes.
- **AEAD**: ChaCha20-Poly1305 from `cryptography.hazmat.primitives.ciphers.aead.ChaCha20Poly1305`.
  - Key: 32 bytes. Nonce: 12 random bytes. No associated data.
  - Wire format: `nonce (12 bytes) || ciphertext || tag (16 bytes)`.

---

## 2. Macaroon Construction

### 2.1 Initial Signature

```
sig₀ = HMAC-SHA256(key=root_key, data=identifier.encode("utf-8"))
```

### 2.2 First-Party Caveat

Appends a predicate string. Chain:
```
sigᵢ = HMAC-SHA256(key=sigᵢ₋₁, data=predicate.encode("utf-8"))
```

Stored as `{"cid": predicate}`.

### 2.3 Third-Party Caveat

1. Generate `crk = os.urandom(32)` (caveat root key).
2. `vid = AEAD-Encrypt(key=sigᵢ₋₁, plaintext=crk)` — the verifier recovers `crk` from this.
3. `ticket = AEAD-Encrypt(key=tp_key, plaintext=crk)` — the third party recovers `crk` from this.
4. Chain: `sigᵢ = HMAC-SHA256(key=sigᵢ₋₁, data=vid || identifier.encode("utf-8"))`.

Stored as `{"cid": identifier, "vid": vid_bytes, "cl": location, "ticket": ticket_bytes}`.

Third-party keys (`tp_key`) must be exactly 32 bytes.

### 2.4 Immutability

`add_first_party_caveat` and `add_third_party_caveat` return a **new** `Macaroon` instance.
The original must remain unchanged.

---

## 3. Discharge Protocol

### 3.1 ThirdPartyDischarger

Given the third party's secret key and a third-party caveat dict:
1. Decrypt `ticket` with `tp_key` to recover `crk`.
2. Create a new `Macaroon(location=..., identifier=caveat["cid"], key=crk)`.
3. The discharger may add its own first-party caveats to the discharge.

### 3.2 Binding (prepare_for_request)

Before submission, a discharge macaroon must be bound to the root macaroon:
```
bound_sig = HMAC-SHA256(key=root_macaroon.signature, data=discharge.signature)
```

`prepare_for_request(root_signature)` returns a new `Macaroon` with the bound signature.

---

## 4. Verification

### 4.1 Verifier

Constructor: `Verifier(revocation_store=None)`.

Methods:
- `satisfy_exact(predicate: str)` — registers an exact-match satisfier.
- `satisfy_general(func: Callable[[str], bool])` — registers a general satisfier.
- `verify(macaroon, key, discharge_macaroons=None) -> bool`.

### 4.2 Verification Algorithm

1. If `revocation_store` is set and `macaroon.identifier` is revoked, return `False`.
2. Walk the caveat chain, recomputing intermediate signatures from `key`:
   - At each **first-party** caveat: check the predicate against satisfiers. If unsatisfied → `False`. Update sig.
   - At each **third-party** caveat: decrypt `vid` with current sig to recover `crk`. Store `(crk, cid)`. Update sig.
3. Compare recomputed final sig with `macaroon.signature` using `hmac.compare_digest`. If mismatch → `False`.
4. For each stored `(crk, cid)`:
   a. Find matching discharge in `discharge_macaroons` by `identifier == cid`.
   b. Walk discharge caveat chain with `crk`, checking each first-party caveat against satisfiers.
   c. Compute expected bound signature: `HMAC-SHA256(key=macaroon.signature, data=computed_discharge_sig)`.
   d. Compare with `discharge.signature` using `hmac.compare_digest`. If mismatch → `False`.
5. Return `True`.

---

## 5. Serialization

- `serialize() -> bytes`: Encode the macaroon as msgpack using `use_bin_type=True`.
- `Macaroon.deserialize(data) -> Macaroon`: Decode with `raw=False`.

Payload structure:
```python
{"location": str, "identifier": str, "caveats": [caveat_dicts], "signature": bytes}
```

Must round-trip all fields faithfully, including binary `vid`/`ticket` fields in third-party caveats.

---

## 6. RevocationStore

- `revoke(identifier: str)` — marks the identifier as revoked.
- `is_revoked(identifier: str) -> bool` — checks revocation status.

Revocation by identifier invalidates the root token **and** all attenuated descendants (they share the same identifier).

---

## 7. CachingVerifier

Subclass of `Verifier`. Constructor: `CachingVerifier(revocation_store=None)`.

- Caches verification results keyed by `macaroon.signature`.
- On verify: check revocation first (even if cached), then check cache, then fall back to full verification.
- `cache_size() -> int`.

---

## 8. TokenService

Constructor: `TokenService(key_store: dict)` where `key_store` maps `identifier -> root_key`.

`derive_service_token(macaroon, strip_predicates: list[str], strip_third_party_locations: list[str]) -> Macaroon`:

1. Look up the root key for `macaroon.identifier`.
2. Create a new `Macaroon` with the same `location`, `identifier`, and root key.
3. Re-add only first-party caveats whose predicate does **not** start with any entry in `strip_predicates`.
4. Skip all third-party caveats (they cannot be re-added without the third party's key; service tokens are meant to operate without third-party authentication).
5. The resulting token has a fresh, valid HMAC chain.

---

## 9. Required Class API Summary

```
Macaroon(location: str, identifier: str, key: bytes)
  .location -> str
  .identifier -> str
  .signature -> bytes  (32 bytes)
  .caveats -> list[dict]
  .add_first_party_caveat(predicate: str) -> Macaroon   # raises ValueError if empty
  .add_third_party_caveat(location: str, key: bytes, identifier: str) -> Macaroon
  .prepare_for_request(root_signature: bytes) -> Macaroon
  .serialize() -> bytes
  Macaroon.deserialize(data: bytes) -> Macaroon

Verifier(revocation_store=None)
  .satisfy_exact(predicate: str)
  .satisfy_general(func)
  .verify(macaroon, key, discharge_macaroons=None) -> bool

ThirdPartyDischarger(key: bytes)
  .discharge(caveat: dict, location: str) -> Macaroon

RevocationStore()
  .revoke(identifier: str)
  .is_revoked(identifier: str) -> bool

CachingVerifier(revocation_store=None)   [extends Verifier]
  .cache_size() -> int

TokenService(key_store: dict)
  .derive_service_token(macaroon, strip_predicates, strip_third_party_locations) -> Macaroon
```
