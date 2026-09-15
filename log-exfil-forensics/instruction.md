A production Linux web server was compromised during a three-day window. Log files at `/app/logs/`:

- `auth.log` — SSH authentication events (syslog format, assume year 2024)
- `access.log` — Apache combined log
- `dns_queries.log` — DNS resolver queries
- `app_audit.log` — Application audit trail

Logs span March 14–16, 2024. Legitimate admin access originates from `10.0.1.0/24`.

A junior analyst previously drafted eight candidate detection rules at `/app/candidate_rules.json`. Some are effective, some produce false positives against legitimate traffic in these logs, and some miss the actual attack technique entirely. You must evaluate all of them against the evidence in the logs.

Produce three output files:

**`/app/incident_report.json`** with fields: `attacker_ip`, `brute_force_start`, `brute_force_success`, `compromised_account`, `webshell_path`, `webshell_first_access`, `exfiltrated_file`, `c2_domain`, `num_dns_exfil_queries`, `decrypted_exfil_sha256`. All timestamps `YYYY-MM-DD HH:MM:SS`. The SHA-256 is the lowercase hex digest of the raw decrypted exfiltrated bytes — the encryption key must be recovered from artifacts scattered across web shell request parameters.

**`/app/rule_evaluation.json`** — JSON object keyed by each candidate `rule_id`. Each value is an object with `verdict` and `justification`. Verdicts: `effective` (detects the attack with zero false positives on legitimate traffic in these logs), `noisy` (detects the attack but also fires on legitimate traffic — identify which entities cause false positives), `ineffective` (fails to detect the actual attack technique used). Evaluate each rule by testing its detection logic against the full log data — do not guess.

**`/app/detection_rules.json`** — JSON array of your own improved detection rules (at least one per stage: `initial_access`, `execution`, `exfiltration`), each with fields: `rule_id`, `stage`, `title`, `log_source`, `detection_logic`, `indicator_value`. Your rules must correctly detect each attack phase without false-positiving on legitimate traffic in these logs.