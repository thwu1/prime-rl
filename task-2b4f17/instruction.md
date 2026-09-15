A vehicle ECU firmware image at `/app/firmware.bin` uses a proprietary binary container format (FWPK) with multi-layer cryptography — RSA for key wrapping and AES for data encryption — protecting diagnostic data across encrypted partitions. One section holds a gzip-compressed Python key management module documenting the encryption scheme, including a key-masking step applied before RSA wrapping. The cryptographic infrastructure has implementation weaknesses enabling full key recovery without any secret knowledge.

An RSA-2048 public key is provided at `/app/hardened_pubkey.pem` for use in Phase 2.

**Phase 1 — Cryptanalysis**: Break the firmware's cryptography and recover all protected data.

- `/app/rsa_private.pem` — the reconstructed RSA private key (PEM format)
- `/app/recovered_data.txt` — the fully recovered and reassembled diagnostic data
- `/app/security_token.txt` — the authentication token value (the value after `Auth Token: `, no trailing newline)

**Phase 2 — Hardened Re-encryption**: Using your understanding of the cryptographic weaknesses you exploited, design and build a hardened replacement firmware container at `/app/hardened_firmware.bin`. The container must use the same FWPK binary format but replace every weak cryptographic primitive with a secure alternative:

- Wrap keys using RSA-OAEP with SHA-256 and the RSA-2048 key at `/app/hardened_pubkey.pem` (replacing PKCS#1 v1.5 with the weak RSA key)
- Protect partition data with AES-256-GCM for authenticated encryption (replacing unauthenticated CBC mode)
- Derive the AES-256 session key deterministically: `SHA-256("hardened-session-key-" || SHA-256(diagnostic_data).hex())`
- Derive each partition's 12-byte GCM nonce: `SHA-256("gcm-nonce-" || str(partition_index))[:12]`
- Store each encrypted partition as: `nonce (12 bytes) || ciphertext || GCM tag (16 bytes)`
- Split diagnostic data into 3 partitions identically to the original: first two are `floor(len/3)` bytes, third is the remainder
- Include sections: manifest (JSON describing the hardened crypto), rsa_pubkey (RSA-2048 DER), wrapped_aeskey, and three partition sections