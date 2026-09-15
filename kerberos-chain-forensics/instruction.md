You are the senior incident response lead for **MERIDIAN.LOCAL**. A breach has been confirmed and forensic artifacts have been staged at `/app/evidence/`. Examine all files and subdirectories within the evidence directory to understand what occurred.

Your CISO requires two deliverables:

## Deliverable 1 — Attack Reconstruction (`/app/answers/attack_analysis.json`)

Analyze all evidence to reconstruct the complete attack chain from initial foothold through domain compromise. Write a JSON object with these fields:
- `initial_compromise` — sAMAccountName of the first compromised user account
- `compromised_service_account` — sAMAccountName of the service account the attacker targeted and compromised next
- `compromised_spn` — The Service Principal Name associated with that service account's compromise
- `recovered_password` — Plaintext password the attacker obtained for the service account
- `exploited_template` — Name of the template that was exploited to escalate privileges
- `vulnerability_class` — Standard classification identifier for the vulnerability that was exploited
- `impersonated_user` — sAMAccountName of the privileged user ultimately impersonated
- `attack_chain_summary` — Narrative of the full attack chain including all techniques used

## Deliverable 2 — Security Posture Assessment (`/app/answers/security_assessment.json`)

Go beyond the observed attack. Audit the entire AD snapshot for exploitable weaknesses, then produce defense artifacts. Write a JSON object with fields:

- `alternative_attack_paths` — Array of objects identifying every other viable privilege escalation path in this environment (beyond the one the attacker actually used). Each entry: `{"path_name": "...", "technique": "...", "entry_account_or_object": "...", "target": "...", "risk_level": "critical|high|medium|low", "justification": "..."}`
- `highest_risk_misconfiguration` — The single most dangerous misconfiguration in the environment and why
- `sigma_rules` — Array of Sigma detection rules (each a YAML string) that would detect the attack techniques observed or available in this environment. Each rule must include `title`, `logsource`, `detection`, and `level` fields.
- `remediation_plan` — Ordered array of remediation actions, each: `{"priority": <int>, "action": "...", "target_object": "...", "specific_change": "...", "rationale": "..."}`

All answers must be derived computationally from the evidence files.