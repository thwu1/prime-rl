Implement Ed25519 (RFC 8032, Section 5.1) as a C library at `/app/`. Running `make` in `/app/` must produce the executable `/app/ed25519_tool`.

The tool accepts three subcommands:

- `./ed25519_tool keygen <hex_secret>` — Print the hex-encoded 32-byte public key derived from the 32-byte secret key.
- `./ed25519_tool sign <hex_secret> <hex_message>` — Print the hex-encoded 64-byte signature. Pass an empty string for an empty message.
- `./ed25519_tool verify <hex_pubkey> <hex_message> <hex_signature>` — Print `VALID` or `INVALID`.

The C implementation must conform to `/app/ed25519.h`:

```c
void ed25519_derive_pubkey(const uint8_t secret[32], uint8_t pubkey[32]);
void ed25519_sign(const uint8_t secret[32], const uint8_t *msg, size_t msg_len,
                  uint8_t signature[64]);
int ed25519_verify(const uint8_t pubkey[32], const uint8_t *msg, size_t msg_len,
                   const uint8_t signature[64]);
```

**Success criteria:**

- All five RFC 8032 Section 7.1 Ed25519 test vectors must pass: key derivation must produce the specified public key, signing must produce the byte-exact deterministic signature, and verification must accept those signatures.
- Verification must reject signatures where the scalar component S is not in the range `[0, L)`, where L is the Ed25519 group order (`2^252 + 27742317777372353535851937790883648493`). This prevents signature malleability.
- Verification must reject tampered signatures (modified R or S bytes) and tampered messages.
- Must handle messages of any length, including zero-length messages.
- Must correctly handle the first 20 entries of the SUPERCOP Ed25519 sign.input test vector set (colon-delimited fields: `secret+pubkey : pubkey : msg : sig+msg`, all hex-encoded).

**Environment:** GCC and OpenSSL development headers (`libssl-dev`) are pre-installed. `<openssl/sha.h>` provides SHA-512. `<openssl/bn.h>` provides arbitrary-precision integer arithmetic. Files under `/app/` may be freely modified or added.
