An organization's RSA key inventory has been exported for security assessment. The directory `/app/keys/` contains public keys in mixed formats (PEM and DER). Hardware provenance and origin metadata is in `/app/metadata.json`. Additional audit context is in `/app/audit_scope.txt`.

For each key, a challenge ciphertext is stored in `/app/challenges/<key_id>.json` as `{"ciphertext": "<decimal>"}`. Each ciphertext was produced by raw textbook RSA encryption (c = m^e mod n) of a 64-bit integer plaintext.

Identify all keys with exploitable cryptographic weaknesses. For each key you can break, recover the private key and decrypt the corresponding challenge.

Write results to:
- `/app/results/audit.json` — object mapping each key ID (e.g. `"cert_01"`) to `{"vulnerable": true}` or `{"vulnerable": false}`
- `/app/results/decrypted.json` — object mapping each broken key ID to the recovered plaintext as a decimal string