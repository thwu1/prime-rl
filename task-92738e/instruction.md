A corpus of secp256k1 ECDSA signatures collected from blockchain transactions is stored at `/app/` across three interconnected formats:

- `/app/corpus.db` — SQLite database with tables `ec_keys`, `ecdsa_signatures`, and `signing_challenges`. Key and signature records reference external files by filename.
- `/app/keys/` — EC public keys as PEM-encoded SubjectPublicKeyInfo files (curve OID 1.3.132.0.10)
- `/app/sigs/` — ECDSA signatures as DER-encoded ASN.1 structures (SEQUENCE of two INTEGERs)

All signatures use BIP-62 low-s normalization (s ≤ n/2).

Correlate the data across all three formats to reconstruct a unified signature dataset. Identify a cryptographic vulnerability in the corpus that allows recovery of the signing private keys, and exploit it to recover each distinct key.

For each challenge in the `signing_challenges` table, produce a valid ECDSA signature using the corresponding recovered private key.

Write `/app/results.json` as a JSON array ordered by `challenge_id`. Each element must contain:

- `"key_pem_file"`: filename of the PEM key from `/app/keys/` (e.g. `"key_1.pem"`)
- `"message_hash"`: 64-char lowercase hex
- `"signature_r"`: 64-char zero-padded lowercase hex
- `"signature_s"`: 64-char zero-padded lowercase hex, low-s normalized

Also produce DER-encoded signature files at `/app/output/challenge_1.der`, `/app/output/challenge_2.der`, and `/app/output/challenge_3.der`, each containing the corresponding signature encoded as ASN.1 SEQUENCE { INTEGER r, INTEGER s }.