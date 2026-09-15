An organization's vault security daemon encrypted audit log entries using three successive encryption engines over its lifecycle. All entries are persisted in an SQLite database at `/app/data/audit.db`. Engine implementations are at `/app/vault_logger/engines/`, with supporting modules in `/app/vault_logger/`. A signed deployment manifest at `/app/config/deployment_manifest.json` (signature at `/app/config/deployment_manifest.sig`, public key at `/app/keys/vault_pub.pem`) records each engine's activation timeline.

A sensitive API token (`ROOT_API_TOKEN`) was logged as a `SECRET`-type entry somewhere in the database. The current engine's key is HSM-managed and unavailable. A wrapped export of the v1 engine's key exists at `/app/keys/v1_wrapped.bin`, and the RSA private key that can unwrap it is at `/app/keys/vault_priv.pem`.

Recover the API token and produce a complete security assessment of all three engines along with a remediation system for the vulnerable data. Deliverables:

1. `/app/solution.txt` — the recovered token (`tk_...` string only)
2. `/app/audit_report.json` — JSON object:
   - `engines`: array of 3 objects, each with `version` (int), `cipher_suite` (string), `vulnerability_class` (`"CRITICAL"` | `"HIGH"` | `"MEDIUM"` | `"LOW"` | `"NONE"`), `weakness_description` (string), `collision_probability` (float in [0,1]: probability of nonce/ciphertext collision given the observed entry volume and engine design), `data_at_risk_count` (int: entries whose plaintext is recoverable given available key material and observable ciphertext properties)
   - `recovered_secrets`: array of recovered plaintext secret strings
   - `recommended_engine`: int (most secure version)
3. `/app/remediation/secure_engine.py` — Python module exposing a `SecureEngine(master_key: bytes, context: str)` class with `encrypt(plaintext: bytes) -> bytes` and `decrypt(ciphertext: bytes) -> bytes`. Must provide authenticated encryption with per-context key isolation derived from the master key.
4. `/app/remediation/migrate.py` — executable script that decrypts all v1 entries and re-encrypts them via your `SecureEngine` using master key at `/app/remediation/migration_key.bin` with context `"v1-migration"`, writing results to a `migrated_entries` table in the audit database (columns: `original_id` INTEGER, `ciphertext` BLOB).
5. `/app/remediation/migration_key.bin` — 32-byte master key for the migration.