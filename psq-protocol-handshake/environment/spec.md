# PSQ Protocol Specification — DH-Based Registration Mode


## Overview

The PSQ (Post-Quantum Pre-Shared-Key) protocol establishes a shared secret
between an initiator `I` and a responder `R`. This document specifies the
**DH-based registration mode** for the ciphersuite
`X25519_NONE_X25519_CHACHA20POLY1305_HKDFSHA256`.

## Ciphersuite Components

- **DH (Outer & Inner)**: X25519 (RFC 7748)
- **PQ-KEM**: NONE (no post-quantum KEM in this ciphersuite)
- **AUTH**: X25519 DH-based initiator authentication
- **AEAD**: ChaCha20-Poly1305 (RFC 8439)
- **KDF**: HKDF-SHA256 (RFC 5869)
- **Hash**: SHA-256

## Cryptographic Primitives

### KDF(ikm, info)
```
KDF(ikm, info) = HKDF-Expand(HKDF-Extract(salt=b"", ikm), info, 32)
```
where:
- `HKDF-Extract(salt, ikm) = HMAC-SHA256(key=salt, msg=ikm)`
- When salt is empty bytes (`b""`), use a zero-key of 32 bytes as the HMAC key
- `HKDF-Expand(prk, info, L)`: for L=32, output = `HMAC-SHA256(key=prk, msg=info || 0x01)`

### AEAD.Encrypt(K, plaintext, aad) / AEAD.Decrypt(K, ciphertext_with_tag, aad)
ChaCha20-Poly1305 per RFC 8439:
- Key: 32 bytes (from KDF)
- Nonce: 12 bytes, all zeros (`b'\x00' * 12`) — safe because each key is used exactly once
- Output of Encrypt: ciphertext || 16-byte authentication tag

### DH.KeyGen() / DH.Derive(sk, pk)
X25519 per RFC 7748:
- Private keys: 32 bytes, clamped per RFC 7748 Section 5
- Public keys: 32 bytes
- `DH.KeyGen()`: clamp private key, multiply by base point 9
- `DH.Derive(sk, pk)`: X25519 scalar multiplication

### hash(...)
SHA-256, producing a 32-byte digest.

## Serialization Format

All hash and KDF inputs use the following serialization:

### Fixed-size values
- DH public keys (32 bytes): raw bytes, no length prefix
- Transcript hashes (32 bytes): raw bytes, no length prefix
- Mode bytes: single byte (`\x00`, `\x01`, or `\x02`)

### Variable-length values
- `context`: 2-byte big-endian length prefix followed by the context bytes
- `ctxt_inner` (in outer message): 2-byte big-endian length prefix followed by ciphertext bytes
- `registration_inner_aad` (in outer message): 2-byte big-endian length prefix followed by AAD bytes

### Optional values
- Optional fields use a 1-byte presence flag: `\x00` if absent, `\x01` followed by the value if present
- In the `NONE` ciphersuite: `pqek_S`, `enc_pq`, and `ss_pq` are all absent

### KDF input concatenation
- When KDF receives multiple key materials (e.g., `K_0 | ss_dh_inner`), they are simply concatenated as raw bytes

## Protocol Flow — DH-Based Registration Mode

### Initiator (I) Processing

```
Inputs:
    (priv_I, pub_I)      — long-term DH key pair
    (epriv_I, epub_I)    — ephemeral DH key pair
    pub_R                — responder's long-term DH public key
    context              — protocol context bytes
    registration_payload — application payload to send
    registration_inner_aad — AAD for inner encryption
    registration_outer_aad — AAD for outer encryption

Step 1: Compute tx0
    tx0 = hash(0x00 || len_prefix(context) || pub_R || epub_I)

Step 2: Compute K_0
    ss_dh_outer = DH.Derive(epriv_I, pub_R)
    K_0 = KDF(ss_dh_outer, tx0)

Step 3: Compute tx1 (no PQ-KEM)
    tx1 = hash(0x01 || tx0 || pub_I || optional(None) || optional(None))
    where optional(None) = 0x00

Step 4: Compute K_1
    ss_dh_inner = DH.Derive(priv_I, pub_R)
    K_1 = KDF(K_0 || ss_dh_inner, tx1)

Step 5: Encrypt inner payload
    ctxt_inner = AEAD.Encrypt(K_1, registration_payload, registration_inner_aad)

Step 6: Encrypt outer message
    outer_plaintext = pub_I || len_prefix(ctxt_inner) || len_prefix(registration_inner_aad) || optional(None)
    ctxt_outer = AEAD.Encrypt(K_0, outer_plaintext, registration_outer_aad)

I -> R: (epub_I, ctxt_outer, registration_outer_aad)
```

### Responder (R) Processing

```
Inputs:
    (priv_R, pub_R)      — long-term DH key pair
    (epriv_R, epub_R)    — ephemeral DH key pair
    response_payload     — application response payload
    response_aad         — AAD for response encryption

Step 1: Recompute tx0 and K_0
    tx0 = hash(0x00 || len_prefix(context) || pub_R || epub_I)
    ss_dh_outer = DH.Derive(priv_R, epub_I)
    K_0 = KDF(ss_dh_outer, tx0)

Step 2: Decrypt outer message
    outer_plaintext = AEAD.Decrypt(K_0, ctxt_outer, registration_outer_aad)
    Parse: pub_I || len_prefix(ctxt_inner) || len_prefix(registration_inner_aad) || optional(enc_pq)

Step 3: Recompute tx1 and K_1
    tx1 = hash(0x01 || tx0 || pub_I || optional(None) || optional(None))
    ss_dh_inner = DH.Derive(priv_R, pub_I)
    K_1 = KDF(K_0 || ss_dh_inner, tx1)

Step 4: Decrypt inner payload
    registration_payload = AEAD.Decrypt(K_1, ctxt_inner, registration_inner_aad)

Step 5: Compute tx2
    tx2 = hash(0x02 || tx1 || epub_R)

Step 6: Compute K_2
    ss_dh_response_1 = DH.Derive(epriv_R, pub_I)
    ss_dh_response_2 = DH.Derive(epriv_R, epub_I)
    K_2 = KDF(K_1 || ss_dh_response_1 || ss_dh_response_2, tx2)

Step 7: Encrypt response
    ctxt_response = AEAD.Encrypt(K_2, response_payload, response_aad)

R -> I: (epub_R, ctxt_response, response_aad)
```

### Initiator Verifies Response

```
Step 1: Recompute tx2, K_2
    tx2 = hash(0x02 || tx1 || epub_R)
    ss_dh_response_1 = DH.Derive(priv_I, epub_R)
    ss_dh_response_2 = DH.Derive(epriv_I, epub_R)
    K_2 = KDF(K_1 || ss_dh_response_1 || ss_dh_response_2, tx2)

Step 2: Decrypt response
    response_payload = AEAD.Decrypt(K_2, ctxt_response, response_aad)
```

## Session Derivation

After the handshake, both parties derive session keys from `K_2` and `tx2`:

```
K_S = KDF(K_2, "session key" || tx2)

session_ID = KDF(K_S, "shared key id")

pk_binder = KDF(K_S, pub_I || pub_R)
```

Note: string literals like `"session key"` are encoded as raw ASCII bytes (no length prefix, no null terminator).

### Channel Keys

Bidirectional channel keys for channel number `n` (4-byte big-endian unsigned integer):

```
K_i2r_n = KDF(K_S, "i2r channel key" || pk_binder || uint32_be(n))
K_r2i_n = KDF(K_S, "r2i channel key" || pk_binder || uint32_be(n))
```

### Secret Export

```
K_export = KDF(K_S, export_context || "PSQ secret export")
```

where `export_context` is application-defined bytes.

### Session Import (Rekey)

Given an external pre-shared key `psk`:

```
K_import = KDF(K_S || psk, "secret import")
tx' = hash(tx2 || session_ID)
K_S' = KDF(K_import, "session secret" || tx')
session_ID' = KDF(K_S', "shared key id")
```

## Output JSON Schema

Write to `/app/output.json` with this exact structure:

```json
{
  "intermediate": {
    "ss_dh_outer": "<hex>",
    "ss_dh_inner": "<hex>",
    "ss_dh_response_1": "<hex>",
    "ss_dh_response_2": "<hex>",
    "tx0": "<hex>",
    "tx1": "<hex>",
    "tx2": "<hex>",
    "K_0": "<hex>",
    "K_1": "<hex>",
    "K_2": "<hex>",
    "ctxt_inner": "<hex>"
  },
  "session": {
    "K_S": "<hex>",
    "session_ID": "<hex>",
    "pk_binder": "<hex>",
    "K_i2r_0": "<hex>",
    "K_r2i_0": "<hex>",
    "K_i2r_1": "<hex>",
    "K_r2i_1": "<hex>",
    "K_export": "<hex>"
  },
  "rekey": {
    "K_import": "<hex>",
    "tx_prime": "<hex>",
    "K_S_prime": "<hex>",
    "session_ID_prime": "<hex>"
  }
}
```

All values are lowercase hexadecimal strings.
