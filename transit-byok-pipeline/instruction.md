An OpenBao server environment is pre-configured at `/app/`:
- Server configuration: `/app/bao-config.hcl` (file-based storage at `/app/bao-data`)
- Pre-generated private keys: `/app/keys/rsa4096.pem` (RSA-4096) and `/app/keys/ed25519.pem` (ed25519)
- Plaintext data: `/app/data/records.json` (5 records; `rec-001` and `rec-005` share identical data values)

Bring up the OpenBao instance, configure its Transit secrets engine with four named keys, process the records through the engine, and produce output artifacts as described below. The full initialization JSON (containing `unseal_keys_b64` and `root_token`) must be persisted at `/app/state/init.json`.

## Required Key State (Transit engine)

After all operations complete, the Transit engine must contain exactly these keys in the specified states:

| Key | Type | Requirements |
|---|---|---|
| `data-enc` | aes256-gcm96 | convergent encryption and key derivation enabled; `latest_version`=4; `min_decryption_version`=3; `min_encryption_version`=4 |
| `hmac-auth` | hmac | `key_size`=64 |
| `imported-rsa` | rsa-4096 | Must use the private key from `/app/keys/rsa4096.pem`; `exportable`=true; `allow_plaintext_backup`=true |
| `imported-ed25519` | ed25519 | Must use the private key from `/app/keys/ed25519.pem`; `latest_version`=1 |

## Required Outputs (`/app/output/`)

**`encrypted_records.json`** — All 5 records encrypted under `data-enc` with each record's `id` used as the convergent encryption context. Every ciphertext must be at key version 4 and must decrypt back to the original plaintext.
Format: `{"records": [{"id": "...", "ciphertext": "vault:v4:..."}]}`

**`signatures.json`** — Each record's final ciphertext string signed by `imported-ed25519`. Signatures must verify.
Format: `{"signatures": [{"id": "...", "signature": "vault:v1:..."}]}`

**`hmacs.json`** — SHA2-512 HMAC of each record's original plaintext via `hmac-auth`. HMACs must verify.
Format: `{"hmacs": [{"id": "...", "hmac": "vault:v1:..."}]}`

**`rsa_public_key.pem`** — Exported public key of `imported-rsa` (latest version), PEM-encoded.

**`key_status.json`** — `{"keys": [...]}` with one entry per Transit key. Each entry must include: `name`, `type`, `latest_version`, `min_decryption_version`, `min_encryption_version`, `supports_encryption`, `supports_signing`, `exportable`, `allow_plaintext_backup`.