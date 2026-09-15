You have inherited artifacts from a partially-completed penetration test against the ACME Corp Active Directory domain (`acme.corp`). The original tester was pulled off the engagement before completing their analysis. Two team members reviewed the artifacts and proposed **competing hypotheses** about the attack path — your job is to determine which is correct, complete the credential recovery, and produce a comprehensive security assessment.

Artifacts are in `/app/`. Read `/app/engagement_notes.txt` for the full artifact inventory, the two competing hypotheses, and context.

Key artifacts include: Responder NTLMv2 captures, Kerberoasting output (with malformed entries requiring filtering), four encrypted packages (each encrypted with AES-256-GCM using a PBKDF2-derived key from a credential obtained during the engagement — you must determine which credential opens each and which contain engagement-relevant data vs. decoys), an AD configuration export, Windows Security event logs from DC01, a network topology map, and an organization-specific wordlist.

Write your complete analysis to `/app/results.json`:

```json
{
  "all_credentials": {"username": "password", ...},
  "selected_hypothesis": "A" or "B",
  "hypothesis_justification": "Evidence-based explanation referencing specific event log entries...",
  "attack_chain": [
    {"stage": N, "technique": "...", "account": "...", "credential_type": "...", "evidence": "...", "next_step": "..."}
  ],
  "vulnerability_assessment": [
    {
      "id": "VULN-N",
      "title": "...",
      "severity": "critical|high|medium|low",
      "cvss_base_score": N.N,
      "misconfiguration": "specific AD config finding...",
      "attack_stage_enabled": N,
      "remediation": "..."
    }
  ],
  "remediation_plan": [
    {"priority": N, "action": "...", "addresses": ["VULN-N", ...], "depends_on": []}
  ],
  "domain_admin": {"username": "...", "password": "...", "ntlm_hash": "..."},
  "objective": "<full content of the decrypted final objective>"
}
```

The `vulnerability_assessment` must identify misconfigurations from `/app/ad_config.json` that enabled each attack stage, with CVSS v3.1 base scores consistent with the severity rating. The `remediation_plan` must order fixes accounting for operational dependencies (e.g., you cannot safely rotate credentials before identifying all compromised accounts). The `ntlm_hash` must be the hex-encoded NTLM hash (MD4 of UTF-16LE password) of the domain admin.