An iperf3 server (v3.16, OpenSSL 3.0.2) with RSA client authentication was compromised on an internal network. The RSA private key, credential store, and captured authentication tokens have been recovered. Four ESnet security advisories covering authentication-related CVEs are available. Conduct forensic analysis, evaluate the protocol's security posture, design a hardened replacement, and migrate existing credentials.

## Environment

- `/app/iperf3_auth_src/` — iperf3 authentication C source (`iperf_auth.c`, `iperf_auth.h`, `t_auth.c`)
- `/app/forensics/` — Recovered RSA keys (`private.pem`, `public.pem`), captured tokens (`captured_tokens.json`), credential store (`authorized_users.csv`), password wordlist (`wordlist.txt`)
- `/app/advisories/` — ESnet security advisories for CVE-2024-26306, CVE-2024-53580, CVE-2025-54349, CVE-2025-54350
- `/app/server_config.json` — Deployment configuration

## Deliverables

**`/app/forensics_report.json`** — Decrypt each captured token using the recovered private key and the protocol defined in the C source. Validate credentials against the store. Crack passwords using the wordlist and iperf3's hashing scheme. Report shared passwords (sorted user groups), chronological token ordering, and anomalous timeline gaps (>10x median inter-token gap).

Schema: `{tokens: [{id, username, password, timestamp, timestamp_utc, valid_user, valid_credentials}], password_audit: {cracked: {user: pw}, uncracked: [users], total_users, cracked_count}, shared_passwords: [[sorted_users]], timeline: {chronological_order: [ids], time_span_seconds, anomalous_gaps: [{between_tokens: [id1,id2], gap_seconds}]}}`

**`/app/security_assessment.json`** — Evaluate the iperf3 authentication protocol. Identify at least 6 distinct vulnerabilities across cryptographic, protocol-design, and implementation categories. Cross-reference with provided CVE advisories where applicable. Assess exploitability given the specific deployment described in `server_config.json`. Include an overall risk rating with justification.

Schema: `{vulnerabilities: [{id, title, category, severity, cve_references, affected_function, description, exploitability, impact, recommendation}], overall_risk_rating, risk_justification}`

**`/app/hardened_auth.py`** — Hardened Python authentication module addressing all identified weaknesses. Required API:
- `generate_keypair()` → `(private_pem_bytes, public_pem_bytes)`
- `encode_token(username, password, public_key_pem)` → base64 token string
- `decode_token(token_str, private_key_pem)` → dict `{username, password, timestamp, nonce}`
- `create_credential_store(users_dict, store_path)` — `users_dict` maps username→password
- `verify_credentials(username, password, store_path)` → bool
- `migrate_credentials(old_csv_path, password_map, new_store_path)` — `password_map` maps username→plaintext

Must use RSA-OAEP (not PKCS1v1.5), a memory-hard KDF (argon2id or bcrypt) for password storage, and a random nonce in every token.

**`/app/migrated_credentials.txt`** and **`/app/migration_report.json`** — Migrate `/app/forensics/authorized_users.csv` to hardened format using cracked passwords from your forensic analysis. Migration report must include `migrated_count` and `total_users`.