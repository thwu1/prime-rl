You are a senior penetration tester completing post-exploitation credential forensics for Meridian Technologies. Your predecessor was reassigned mid-engagement, leaving raw artifacts and partial notes at `/app/engagement/`:

- `notes.txt` — Engagement notes: network topology, identified personnel, observations
- `honeypot_captures.log` — Cleartext credentials captured by a network honeypot
- `server_shadow.txt` — Linux shadow file extract
- `domain_hashes.txt` — Windows domain hash dump
- `webapp_db_dump.csv` — Web application user database extract
- `engagement_wordlist.txt` — Custom wordlist from OSINT and internal documentation
- `password_policy.txt` — Corporate password policy
- `locked_archive.zip` — Password-protected archive from a domain controller file share
- `classified_data.gpg` — Symmetrically encrypted classified file

Analyze all artifacts, infer the organizational password construction pattern from the honeypot data, identify and crack the hash formats used by each system, correlate personnel identities across systems, and follow the credential chain through the encrypted vault to recover the classified file. Write your complete analysis to `/app/results/report.json`:

```json
{
  "cracked_credentials": {
    "<system>:<username>": "<password>"
  },
  "password_pattern": {
    "years": ["<year>", "..."],
    "symbols": ["<symbol_char>", "..."],
    "description": "<how organizational passwords are constructed>"
  },
  "identity_groups": [
    {"person": "<full name>", "accounts": ["<system>:<username>", "..."]}
  ],
  "cross_system_reuse": [
    {"password": "<password>", "accounts": ["<system>:<username>", "..."], "risk_level": "<critical|high|medium>"}
  ],
  "decrypted_flag": "<decrypted classified file contents>"
}
```

System labels are `linux`, `domain`, `webapp`. Include every crackable account in `cracked_credentials` — skip locked/disabled system accounts. The `password_pattern` must describe the construction scheme inferred from honeypot captures, listing all observed year variants and trailing symbols. The `identity_groups` array maps named personnel (by full name) to their accounts across systems using information from the engagement notes. The `cross_system_reuse` array identifies passwords shared across different systems — rate as `critical` when reuse spans three or more systems or involves both service and personal accounts, `high` otherwise.