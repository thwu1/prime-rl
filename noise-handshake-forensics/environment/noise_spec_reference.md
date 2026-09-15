# Noise Protocol Framework - Algorithmic Reference

This is a condensed reference for implementing the Noise Protocol Framework.
Full specification: https://noiseprotocol.org/noise.html (Revision 34, 2018-07-11)

## 1. Crypto Functions

### DH Functions (Curve25519)
- `GENERATE_KEYPAIR()`: Generate a Curve25519 key pair
- `DH(key_pair, public_key)`: X25519 scalar multiplication
- `DHLEN = 32`

### Cipher Functions

**ChaCha20-Poly1305 ("ChaChaPoly")**:
- `ENCRYPT(k, n, ad, plaintext)`: ChaCha20-Poly1305 AEAD. Returns ciphertext + 16-byte tag.
- `DECRYPT(k, n, ad, ciphertext)`: Decrypt and verify.
- Nonce encoding: 4 zero bytes + 8-byte **little-endian** encoding of `n` (12 bytes total)

**AES-256-GCM ("AESGCM")**:
- `ENCRYPT(k, n, ad, plaintext)`: AES-256-GCM AEAD. Returns ciphertext + 16-byte tag.
- `DECRYPT(k, n, ad, ciphertext)`: Decrypt and verify.
- Nonce encoding: 4 zero bytes + 8-byte **big-endian** encoding of `n` (12 bytes total)

### Hash Functions

| Name    | HASHLEN | BLOCKLEN |
|---------|---------|----------|
| SHA256  | 32      | 64       |
| SHA512  | 64      | 128      |
| BLAKE2s | 32      | 64       |
| BLAKE2b | 64      | 128      |

### HMAC and HKDF

**HMAC-HASH(key, data)**: Standard HMAC (RFC 2104) using the selected HASH function.

**HKDF(chaining_key, input_key_material, num_outputs)**:
```
temp_key = HMAC-HASH(chaining_key, input_key_material)
output1  = HMAC-HASH(temp_key, byte(0x01))
output2  = HMAC-HASH(temp_key, output1 || byte(0x02))
if num_outputs == 2: return (output1, output2)
output3  = HMAC-HASH(temp_key, output2 || byte(0x03))
return (output1, output2, output3)
```
All outputs are HASHLEN bytes.

## 2. Processing Rules

### CipherState

Variables: `k` (32-byte key or empty), `n` (64-bit unsigned integer nonce)

- `InitializeKey(key)`: Set `k = key`, `n = 0`
- `HasKey()`: True if `k` is non-empty
- `EncryptWithAd(ad, plaintext)`: If `k` non-empty, return `ENCRYPT(k, n++, ad, plaintext)`. Otherwise return `plaintext`.
- `DecryptWithAd(ad, ciphertext)`: If `k` non-empty, return `DECRYPT(k, n++, ad, ciphertext)`. Otherwise return `ciphertext`.

### SymmetricState

Contains a CipherState plus: `ck` (chaining key, HASHLEN bytes), `h` (hash, HASHLEN bytes)

- `InitializeSymmetric(protocol_name)`:
  - If `len(protocol_name) <= HASHLEN`: `h = protocol_name` padded with zeros to HASHLEN
  - Otherwise: `h = HASH(protocol_name)`
  - `ck = h`
  - `InitializeKey(empty)`

- `MixKey(input_key_material)`:
  - `ck, temp_k = HKDF(ck, input_key_material, 2)`
  - If HASHLEN == 64, truncate `temp_k` to 32 bytes
  - `InitializeKey(temp_k)`

- `MixHash(data)`: `h = HASH(h || data)`

- `MixKeyAndHash(input_key_material)` (for PSK mode):
  - `ck, temp_h, temp_k = HKDF(ck, input_key_material, 3)`
  - `MixHash(temp_h)`
  - If HASHLEN == 64, truncate `temp_k` to 32 bytes
  - `InitializeKey(temp_k)`

- `EncryptAndHash(plaintext)`:
  - `ciphertext = EncryptWithAd(h, plaintext)`
  - `MixHash(ciphertext)`
  - Return `ciphertext`

- `DecryptAndHash(ciphertext)`:
  - `plaintext = DecryptWithAd(h, ciphertext)`
  - `MixHash(ciphertext)`
  - Return `plaintext`

- `Split()`:
  - `temp_k1, temp_k2 = HKDF(ck, zerolen, 2)` (zerolen = empty byte sequence)
  - If HASHLEN == 64, truncate both to 32 bytes
  - Create `c1`, `c2` as new CipherState objects
  - `c1.InitializeKey(temp_k1)`, `c2.InitializeKey(temp_k2)`
  - Return `(c1, c2)` — c1 for initiator→responder, c2 for responder→initiator

- `GetHandshakeHash()`: Return `h`

### HandshakeState

Variables: `s, e` (local key pairs), `rs, re` (remote public keys), `initiator` (boolean), `message_patterns` (remaining patterns)

- `Initialize(handshake_pattern, initiator, prologue, s, e, rs, re)`:
  1. Build protocol_name string, call `InitializeSymmetric(protocol_name)`
  2. `MixHash(prologue)`
  3. For each public key in the initiator's pre-message: `MixHash(public_key)`
  4. For each public key in the responder's pre-message: `MixHash(public_key)`
     (Initiator's pre-message keys are hashed first)

- `WriteMessage(payload, message_buffer)`:
  1. Pop next message pattern, process each token:
     - `"e"`: Set `e = GENERATE_KEYPAIR()`, append `e.public_key` to buffer, `MixHash(e.public_key)`. **In PSK mode: also `MixKey(e.public_key)`**
     - `"s"`: Append `EncryptAndHash(s.public_key)` to buffer
     - `"ee"`: `MixKey(DH(e, re))`
     - `"es"`: If initiator: `MixKey(DH(e, rs))`. If responder: `MixKey(DH(s, re))`
     - `"se"`: If initiator: `MixKey(DH(s, re))`. If responder: `MixKey(DH(e, rs))`
     - `"ss"`: `MixKey(DH(s, rs))`
     - `"psk"`: `MixKeyAndHash(psk)`
  2. Append `EncryptAndHash(payload)` to buffer
  3. If no more patterns, return `Split()`

- `ReadMessage(message, payload_buffer)`:
  1. Pop next message pattern, process each token:
     - `"e"`: Read `DHLEN` bytes → `re`, `MixHash(re)`. **In PSK mode: also `MixKey(re)`**
     - `"s"`: Read `DHLEN + 16` bytes (if HasKey) or `DHLEN` bytes → temp. `rs = DecryptAndHash(temp)`
     - DH tokens and `"psk"`: same as WriteMessage
  2. `DecryptAndHash(remaining)` → payload
  3. If no more patterns, return `Split()`

## 3. Protocol Names

Format: `Noise_PATTERN_DH_CIPHER_HASH`

Examples:
- `Noise_XX_25519_ChaChaPoly_BLAKE2s`
- `Noise_IK_25519_AESGCM_SHA256`
- `Noise_NNpsk0_25519_ChaChaPoly_SHA256`

## 4. Handshake Patterns

### One-way patterns

```
N:                  K:                  X:
  <- s                -> s                <- s
  ...                 <- s                ...
  -> e, es            ...                 -> e, es, s, ss
                      -> e, es, ss
```

### Fundamental interactive patterns

```
NN:                 KN:                 XN:                 IN:
  -> e                -> s                -> e                -> e, s
  <- e, ee            ...                 <- e, ee            <- e, ee, se
                      -> e                -> s, se
                      <- e, ee, se

NK:                 KK:                 XK:                 IK:
  <- s                -> s                <- s                <- s
  ...                 <- s                ...                 ...
  -> e, es            ...                 -> e, es            -> e, es, s, ss
  <- e, ee            -> e, es, ss        <- e, ee            <- e, ee, se
                      <- e, ee, se        -> s, se

NX:                 KX:                 XX:                 IX:
  -> e                -> s                -> e                -> e, s
  <- e, ee, s, es     ...                 <- e, ee, s, es     <- e, ee, se, s, es
                      -> e                -> s, se
                      <- e, ee, se, s, es
```

## 5. PSK Mode

The `pskN` modifier inserts a `"psk"` token:
- `psk0`: at the **beginning** of the first message pattern
- `psk1`, `psk2`, ...: at the **end** of message pattern 1, 2, ...

In PSK handshakes, **all** `"e"` tokens (in pre-messages and message patterns) are followed by `MixKey(e.public_key)` in addition to `MixHash(e.public_key)`.

The `"psk"` token is processed by calling `MixKeyAndHash(psk)`.

## 6. Concrete Functions Summary

| Spec Name   | Algorithm              | Key Size | Output |
|-------------|------------------------|----------|--------|
| 25519       | Curve25519 (X25519)    | 32 bytes | 32 bytes |
| ChaChaPoly  | ChaCha20-Poly1305      | 32 bytes | +16 tag |
| AESGCM      | AES-256-GCM            | 32 bytes | +16 tag |
| SHA256      | SHA-256                | -        | 32 bytes |
| SHA512      | SHA-512                | -        | 64 bytes |
| BLAKE2s     | BLAKE2s                | -        | 32 bytes |
| BLAKE2b     | BLAKE2b                | -        | 64 bytes |
