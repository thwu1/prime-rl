A signing server's audit log has been leaked. The directory `/app/data/` contains:

- `params.pem` — DSA domain parameters in PEM format (inspectable with `openssl dsaparam`)
- `keys/alpha.pub.pem`, `keys/beta.pub.pem`, `keys/gamma.pub.pem` — Three DSA public keys in SubjectPublicKeyInfo PEM format (inspectable with `openssl pkey`)
- `audit.db` — SQLite database with table `audit_log` (columns: `id INTEGER`, `timestamp TEXT`, `message TEXT`, `signature_der BLOB`) where each signature BLOB is a DER-encoded ASN.1 DSA-Sig-Value (SEQUENCE of two INTEGERs: r and s)
- `challenges.json` — Three challenge messages requiring forged signatures, each specifying a target key ID

The audit log holds 15 DSA signatures (SHA-1 hash function) over plaintext messages. Signatures are shuffled across all three keys with no key attribution. The signing implementation is known to be flawed — its private keys are recoverable from the signatures in the audit log.

Recover all three private keys and forge valid DSA signatures for each challenge message under its specified target key.

Write results to `/app/results/`:

- `alpha.priv.pem`, `beta.priv.pem`, `gamma.priv.pem` — Recovered private keys as traditional OpenSSL DSA PEM files (`BEGIN DSA PRIVATE KEY` header, body is DER-encoded SEQUENCE of six INTEGERs: version=0, p, q, g, y, x)
- `forged_0.der`, `forged_1.der`, `forged_2.der` — Forged DSA signatures as raw DER-encoded DSA-Sig-Value (SEQUENCE { INTEGER r, INTEGER s }), indexed by challenge ID
- `results.json`:
```json
{
  "recovered_private_keys": {"alpha": "0x...", "beta": "0x...", "gamma": "0x..."},
  "forged_signatures": [
    {"challenge_id": 0, "r": "0x...", "s": "0x..."},
    {"challenge_id": 1, "r": "0x...", "s": "0x..."},
    {"challenge_id": 2, "r": "0x...", "s": "0x..."}
  ]
}
```