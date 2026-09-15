Production web server `prod-web-01` was taken offline after the SOC detected anomalous outbound connections to unknown external infrastructure. A forensic snapshot is preserved at `/app/evidence/`, containing application source, server logs, shell histories for multiple users, SSH key material, crontab exports, systemd units, network/process captures, and an unidentified binary.

Authorized security testing may have occurred the same day — not all suspicious indicators are malicious. Distinguish genuine compromise artifacts from benign activity.

Produce three deliverables:

1. **`/app/incident_report.json`** — Threat actor infrastructure, complete intrusion chain (initial access through privilege escalation to root), all persistence mechanisms, and exfiltrated data with recovery. Include a `false_positives` key with reasoning for each dismissed indicator.

2. **`/app/detection.yar`** — YARA rules targeting the threat actor's custom tooling and persistence artifacts. Each rule needs a `description` in its `meta` section.

3. **`/app/security_assessment.json`** — Evaluate the organization's security posture and design forward-looking defenses:
   - `control_failure_analysis`: Array. For each attack stage (initial access, credential theft, privilege escalation, persistence, exfiltration), identify the MITRE ATT&CK technique, evaluate what security controls existed or should have existed, explain why each failed, and design a compensating control. Each entry must have: `attack_stage`, `mitre_technique_id`, `mitre_technique_name`, `existing_control`, `failure_reason`, `recommended_control`.
   - `detection_coverage_matrix`: Array. For each MITRE technique identified, assess current detection status (`detected`, `partial`, or `undetected`), the data source that could detect it, and a proposed detection approach. Each entry must have: `mitre_id`, `technique_name`, `current_status`, `required_data_source`, `proposed_detection`.
   - `sigma_rules`: Array of at least 3 Sigma-format detection rules as YAML strings. Each rule must contain `title`, `logsource`, and `detection` sections. Rules must cover: (a) the initial access technique, (b) privilege escalation, and (c) persistence establishment.
   - `architecture_weaknesses`: Array of the top 5 architectural weaknesses that enabled this breach, ranked from most to least critical. Each entry must have: `rank`, `weakness`, `impact_assessment`, `evidence_from_incident`, `remediation`.
   - `overall_maturity`: Object with `score` (integer 1-5) and `justification` explaining the rating based on specific findings from the investigation.