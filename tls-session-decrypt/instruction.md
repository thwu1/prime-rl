During investigation of a server breach, analysts recovered encrypted network session captures, leaked cryptographic private keys, and partial malware reverse engineering results. All artifacts are in `/app/incident/`.

- `captures.json` — four captured encrypted sessions, each containing plaintext handshake messages and a sequence of encrypted records (hex-encoded raw binary)
- `leaked_keys.json` — six recovered private keys from the attacker's staging server; not all correspond to captured sessions
- `context.txt` — analyst notes including malware analysis revealing that some sessions use a modified TLS 1.3 key schedule

The attacker's malware uses TLS 1.3-based encryption (X25519 + AES-128-GCM-SHA256), but some sessions use a non-standard key derivation that skips the early_secret step. The specific modification is documented in `context.txt`. Which sessions use which variant is unknown — determine this through trial decryption.

Design and implement a decryption and forensic analysis tool that handles both protocol variants. Produce the following outputs in `/app/output/`:

- `key_mapping.json` — JSON object mapping each session ID to the ID of the leaked key that decrypts it
- `decrypted/alpha.txt`, `decrypted/beta.txt`, `decrypted/gamma.txt`, `decrypted/delta.txt` — recovered plaintext for each session (skip unrecoverable corrupted records, continue decrypting subsequent records)
- `exfiltration_report.json` — JSON with:
  - `"exfiltrated_sessions"`: sorted list of session IDs containing sensitive data (credentials, PII, or internal secrets)
  - `"benign_sessions"`: sorted list of session IDs with no sensitive data
- `vulnerability_assessment.json` — JSON with:
  - `"sessions"`: object keyed by session ID, each value containing `"protocol_variant"` (`"standard"` or `"modified"`), `"content_category"` (one of `"credentials"`, `"pii"`, `"internal_docs"`, `"public_info"`), and `"severity"` (one of `"critical"`, `"high"`, `"medium"`, `"low"`). For any session with unrecoverable records, also include `"data_loss": true`.
  - `"shared_server_sessions"`: sorted list of session IDs that connected to the same server (matching server public keys in their ServerHello key_share extensions)
  - `"incident_priority"`: session IDs ordered from most to least critical, reflecting both content sensitivity and protocol risk

Severity criteria: `critical` = leaked production credentials or API keys; `high` = personally identifiable information; `medium` = internal documentation revealing infrastructure; `low` = public or non-sensitive content.

The `cryptography` Python library is available via `pip3 install cryptography`.