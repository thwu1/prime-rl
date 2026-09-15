The PSQ (Post-Quantum Pre-Shared-Key) protocol is a novel cryptographic handshake protocol for establishing shared secrets, inspired by the Noise framework and adapted for post-quantum key encapsulation. The protocol specification is at `/app/spec.md`.

Your task: implement a complete PSQ **DH-based registration mode** handshake for the `X25519_NONE_X25519_CHACHA20POLY1305_HKDFSHA256` ciphersuite in Python. This ciphersuite uses X25519 for all Diffie-Hellman operations, no post-quantum KEM, ChaCha20-Poly1305 for AEAD, and HKDF-SHA256 for key derivation.

You must implement from scratch (using only Python standard library — `hashlib`, `hmac`, `struct`):

1. **X25519** key generation and Diffie-Hellman derivation (RFC 7748)
2. **HKDF-SHA256** extract and expand (RFC 5869) — used as `KDF(ikm, info) = HKDF-Expand(HKDF-Extract(salt=b"", ikm), info, 32)`
3. **ChaCha20-Poly1305** AEAD encryption/decryption (RFC 8439)
4. **PSQ transcript maintenance**: `tx0`, `tx1`, `tx2` hash computations
5. **PSQ multi-layer key derivation**: `K_0` through `K_2` and session keys
6. **PSQ session management**: session key `K_S`, session ID, public key binder, bidirectional channel keys, secret export, and session import/rekey

Fixed inputs are at `/app/inputs.json`. Your implementation must read these inputs, execute the full handshake (both initiator and responder sides), and write all computed cryptographic values to `/app/output.json`.

The serialization format for hash/KDF inputs is specified precisely in `/app/spec.md` under "Serialization Format".

Output must match the exact JSON schema documented at the bottom of `/app/spec.md`.