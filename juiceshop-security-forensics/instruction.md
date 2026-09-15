Forensic artifacts recovered from a compromised OWASP Juice Shop instance are available at `/app/incident/`. Investigate all artifacts to identify exploitable security weaknesses, produce working proof-of-concept exploits for each, and deliver a prioritized threat assessment.

Place all deliverables in `/app/results/`:

- **`cracked_credentials.json`** -- JSON array of `{"email": "...", "password": "...", "role": "..."}` for every user whose password you can recover from the database.

- **`forged_token.txt`** -- A JWT that authenticates as `rsa_lord@juice-sh.op`.

- **`forged_coupon.txt`** -- A coupon code granting at least 80% discount, valid for June 2026.

- **`deleted_accounts.json`** -- JSON array of `{"email": "...", "deletedAt": "..."}` identifying user accounts that were not properly erased from the database despite deletion requests.

- **`decrypted_progress.json`** -- The decrypted JSON content of the encrypted progress blob found among the artifacts.

- **`threat_assessment.json`** -- A JSON object containing:
  - `"findings"`: a list of objects, one per vulnerability exploited. Each must include `"title"` (string), `"severity"` (one of `"critical"`, `"high"`, `"medium"`, `"low"`), `"attack_complexity"` (string describing difficulty), `"business_impact"` (string describing consequences), and `"remediation"` (string with a specific fix recommendation).
  - `"overall_risk_score"`: integer from 1 to 10.
  - `"prioritized_order"`: a list of finding titles ordered from most to least urgent to remediate.