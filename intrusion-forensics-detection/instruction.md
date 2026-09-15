A network capture at `/app/incident.pcap` contains traffic from a sophisticated multi-stage intrusion against an internal network (10.1.1.0/24). The attacker used multiple concurrent covert exfiltration channels — including at least one anti-forensics decoy channel designed to misdirect analysis. Legitimate background traffic is interspersed throughout.

Perform a comprehensive forensic investigation: identify and attribute all attack stages, evaluate each exfiltration channel to distinguish genuine data theft from deception, cross-validate findings across channels, and engineer targeted detection rules.

**1. `/app/forensic_report.json`** — JSON object with exactly these keys:
- `attacker_ip` (string), `compromised_host` (string), `scan_type` (string), `ports_scanned` (int), `open_ports` (sorted int list)
- `exploit_method` (string), `exploit_target_port` (int), `exploit_uri` (string)
- `primary_c2_domain` (string), `primary_exfil_encoding` (string)
- `secondary_exfil_dest` (string — IP of secondary exfil destination), `secondary_exfil_encoding` (string)
- `decoy_domain` (string), `decoy_reason` (string — your rationale for classifying this channel as deceptive)

**2. `/app/decoded_primary.txt`** — Fully decoded data from the primary exfiltration channel.

**3. `/app/decoded_secondary.txt`** — Fully decoded data from the secondary exfiltration channel.

**4. `/app/channel_assessment.json`** — Structured evaluation of all observed exfiltration channels (real and decoy):
- `channels`: array of objects, each with `id` (string), `type` (string), `domain_or_dest` (string), `encoding` (string), `classification` (either `"active_exfiltration"` or `"decoy"`), `data_valid` (boolean)
- `cross_validation`: `{ "primary_secondary_match": bool, "data_sha256": "<sha256 hex digest of the decoded exfiltrated data>" }`

**5. `/app/detection.rules`** — Suricata/Snort IDS rules that detect the genuine exfiltration channels without false-positiving on decoy traffic. Each rule requires a unique `sid` and descriptive `msg`.