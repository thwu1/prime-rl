A junior analyst produced a preliminary incident report at `/app/evidence/preliminary_report.json` based on their initial review of a packet capture at `/app/evidence/incident.pcap`. The capture contains traffic from a small corporate network during a suspected multi-stage intrusion. Senior review has flagged the preliminary report as containing significant factual errors — the analyst misidentified the attacker, misclassified the attack vector, confused legitimate traffic with C2, and underestimated the severity.

Your task has three parts:

**1. Forensic Audit** — Independently analyze the pcap to reconstruct the complete attack chain. Compare your findings against every field in the preliminary report, identify which conclusions are incorrect, and produce a corrected incident report.

**2. Detection Engineering** — Design and write a Suricata IDS ruleset that would detect each distinct phase of the attack (reconnaissance, exploitation, command-and-control, exfiltration). Rules must use valid Suricata syntax and produce alerts when run against the pcap with the pre-installed Suricata engine.

**3. Severity Assessment** — Evaluate each attack phase and assign a severity rating (critical / high / medium / low) with a technical justification grounded in the specific techniques and impacts observed. Consider factors such as stealth, reversibility, blast radius, and dependency chains between phases.

Write your outputs to:

- `/app/output/corrected_report.json` — structured report matching the schema below
- `/app/output/detection.rules` — Suricata ruleset with minimum 4 rules covering all attack phases

## Corrected Report Schema

```json
{
  "attacker_ip": "<string>",
  "victim_ip": "<string>",
  "recon_ports_scanned": [22, 80, "...sorted int list"],
  "recon_ports_open": [22, "...sorted int list"],
  "exploit_vector": "<string: attack type>",
  "exploit_endpoint": "<string: HTTP path>",
  "exploit_parameter": "<string: vulnerable parameter name>",
  "malware_download_url": "<string: full URL>",
  "c2_protocol": "<string: transport protocol used for C2>",
  "c2_domain": "<string: C2 domain>",
  "c2_encoding": "<string: encoding scheme>",
  "c2_commands": ["<ordered list of commands/directives received>"],
  "exfil_method": "<string: protocol used>",
  "exfil_dest_ip": "<string: exfil destination IP>",
  "exfil_encoding": "<string: encoding type>",
  "exfil_key": "<string: encoding key in hex>",
  "exfil_decoded_data": ["<ordered list of decoded data lines>"],
  "preliminary_errors": ["<list of field names from the preliminary report's findings object that contain incorrect values>"],
  "phase_severity": {
    "reconnaissance": {"rating": "<severity>", "justification": "<string>"},
    "exploitation": {"rating": "<severity>", "justification": "<string>"},
    "c2": {"rating": "<severity>", "justification": "<string>"},
    "exfiltration": {"rating": "<severity>", "justification": "<string>"}
  }
}
```

Pre-installed tools: `tshark`, `tcpdump`, `suricata`, `python3`, `pip3`.