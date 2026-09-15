A host on the internal network was compromised during a window when an authorized red team exercise was also running. Border sensor logs and a partially recovered malware artifact have been collected under `/app/evidence/`. Read the SOC analyst's initial triage at `/app/evidence/incident_report.txt` to orient yourself, then conduct a full forensic investigation.

Four suspicious DNS query patterns are present in the logs. Two of them use DNS tunneling via TXT queries with high-entropy encoded subdomains — one is the real C2, the other is the authorized red team exercise. You must evaluate each pattern against the malware code fragment to determine which is the actual threat and which is the sanctioned test. The remaining two patterns are benign tools.

Recover all C2 infrastructure details, reconstruct the complete stolen data, classify every suspicious pattern, and build detection artifacts that discriminate between the real threat and the authorized exercise.

## Evidence

- `/app/evidence/incident_report.txt` — SOC analyst's triage notes and IT Security advisory
- `/app/evidence/logs/dns.log` — Zeek DNS query log (2-hour capture)
- `/app/evidence/logs/http.log` — Zeek HTTP request log
- `/app/evidence/logs/conn.log` — Zeek connection summary log
- `/app/evidence/recovered/svc_update.py.fragment` — Partially recovered Python artifact from the compromised host
- `/app/evidence/clean_sample.py` — Benign Python script from the same host (for baseline comparison)

## Deliverables

### 1. Findings Report — `/app/answers.json`

```json
{
  "c2_dns_domain": "<base domain used for DNS-based C2>",
  "redteam_dns_domain": "<base domain used by the authorized red team exercise>",
  "decoy_domains": ["<benign-but-suspicious domain 1>", "<benign-but-suspicious domain 2>"],
  "threat_classifications": {
    "<suspicious_domain_1>": "<active_c2|authorized_redteam|benign_monitoring|benign_testing>",
    "<suspicious_domain_2>": "<classification>",
    "<suspicious_domain_3>": "<classification>",
    "<suspicious_domain_4>": "<classification>"
  },
  "c2_http_domain": "<domain used for HTTP-based C2>",
  "compromised_host_ip": "<internal IP of the compromised machine>",
  "campaign_id": "<campaign identifier from the C2 initialization>",
  "encryption_key_hex": "<hex-encoded encryption key used by the malware>",
  "exfiltrated_data_sha256": "<SHA-256 hash of the fully recovered plaintext>",
  "dns_exfil_query_count": "<integer: total DNS queries to the C2 domain>",
  "http_exfil_post_count": "<integer: HTTP POST requests carrying exfiltrated data>",
  "beacon_interval_seconds": "<integer: C2 heartbeat interval in seconds>",
  "first_c2_contact_epoch": "<integer: Unix epoch of the earliest C2 communication>"
}
```

Classification values must be exactly one of: `active_c2`, `authorized_redteam`, `benign_monitoring`, `benign_testing`.

### 2. YARA Detection Rule — `/app/detection/implant.yar`

Write a YARA rule that:
- Matches when scanned against `/app/evidence/recovered/svc_update.py.fragment`
- Does **not** match when scanned against `/app/evidence/clean_sample.py`

### 3. Sigma Detection Rule — `/app/detection/c2_dns_tunnel.yml`

Design a Sigma YAML detection rule for the DNS tunneling C2 channel. The rule must:
- Follow the Sigma rule schema (title, logsource, detection, level fields required)
- Target DNS logs (logsource category: dns)
- Detect the specific C2 DNS tunneling pattern without false-positiving on the authorized red team exercise
- Reference indicators specific to the real C2's protocol (e.g., encoding scheme, separator convention, domain name, or query structure)