During a red team engagement against ACME Corp, the blue team deployed honeypot infrastructure alongside production systems. The incident artifacts in `/app/incident/` contain evidence from both genuine attack operations and honeypot interactions, deliberately intermixed. Two encrypted assessment reports exist — only one contains the valid proof flag; the other is a honeypot decoy that will appear valid if the wrong credential chain is followed.

Artifacts in `/app/incident/`:
- `capture.pcap` — Network traffic with authenticated sessions from different source IPs
- `app_database.db` — SQLite database with credential tables and schema metadata
- `shadow_dump.txt` — Shadow file entries from multiple hosts
- `server_access.log` — Web server access log with session metadata
- `loot_archive.zip` — Password-protected evidence archive
- `cipher_fragment.bin` — Binary file with custom-encoded data
- `engagement_report_alpha.gpg` — GPG symmetrically encrypted report
- `engagement_report_beta.gpg` — GPG symmetrically encrypted report
- `recon_wordlist.txt` — Custom engagement wordlist

Produce these deliverables:

- `/app/answer.txt` — The exact proof flag string from the genuine assessment report

- `/app/classification.json` — Artifact source discrimination. JSON with `genuine` and `honeypot` top-level keys, each containing: `pcap_session` (source IP), `database_table` (table name), `shadow_host` (hostname), `encrypted_report` (filename)

- `/app/threat_assessment.json` — Evaluate the incident and the deception infrastructure. JSON with:
  - `critical_entry_credential`: the account name whose compromised password enables the most downstream steps in the attack chain (evaluate credential reuse and dependency across the full chain)
  - `honeypot_primary_indicator`: the specific log field name that most directly distinguishes honeypot sessions from genuine ones
  - `deception_rating`: integer 1–10 rating the honeypot infrastructure's overall deception sophistication
  - `recommended_priority_fix`: the single highest-impact remediation that would prevent this attack chain

- `/app/firewall_rules.sh` — Executable iptables script that defends the network based on your forensic findings: block identified threat sources, protect attacked services with rate limiting, and preserve legitimate service access