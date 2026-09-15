SECURE VAULT SYSTEM v2.1
========================

This vault protects sensitive data using hybrid RSA+AES encryption.

Architecture:
  - RSA-1024 (512-bit primes, e=65537) for key encapsulation
  - AES-128-CTR for data encryption
  - Python random module (MT19937 PRNG) for all random material

Initialization Sequence:
  1. PRNG seeded with master secret (Python random.Random)
  2. Calibration: 624 x getrandbits(32) outputs collected and logged
  3. RSA key generation: generate_prime(rng, 512) called twice for p, q
  4. AES key generation: getrandbits(128) for AES-128 key
  5. Nonce generation: getrandbits(64) for AES-CTR nonce
  6. Flag encrypted with AES-CTR using generated key and nonce
  7. AES key encrypted with RSA public key (textbook RSA, no padding)
  8. RSA private key securely destroyed

Files:
  /app/vault/crypto_utils.py          - Cryptographic utility functions
  /app/vault/data/pubkey.json         - RSA public key (n, e in hex)
  /app/vault/data/encrypted_flag.hex  - AES-CTR encrypted vault contents
  /app/vault/data/encrypted_aes_key.hex - RSA-encrypted AES session key
  /app/vault/data/aes_nonce.hex       - AES-CTR nonce
  /app/vault/data/debug_log.txt       - PRNG calibration diagnostic log

The vault contents can only be accessed with the RSA private key,
which was securely deleted after vault creation.

Security Note: The diagnostic log was accidentally left enabled during
vault initialization. It has been reviewed and contains only obfuscated
calibration data - no sensitive key material is exposed.

Proposed Security Patches:
  /app/vault/patches/patch_a.py       - PRNG state desynchronization
  /app/vault/patches/patch_b.py       - CSPRNG key isolation
  /app/vault/patches/patch_c.py       - Seed hardening via PBKDF2

Three security patches have been proposed by the vault-security-team to
address concerns about the diagnostic log. Each patch targets a different
aspect of the system. See individual patch files for implementation details.
