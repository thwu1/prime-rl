A packet capture at `/app/capture.pcap` contains traffic from a multi-stage network intrusion against an internal web server. A junior analyst has submitted a set of six candidate IDS rules at `/app/proposed_rules/candidate_rules.txt` intended to detect this attack. Your job is to perform forensic reconstruction, critically evaluate the proposed rules against the evidence, and engineer an improved detection ruleset.

## Deliverables

### 1. `/app/report/findings.json`

JSON object with these exact keys:

- `attacker_ip` — threat actor's IP address
- `victim_ip` — compromised host's IP address
- `c2_dns_server` — IP of the DNS server used for data exfiltration
- `tunnel_domain` — base domain used for DNS tunneling (parent domain under which encoded subdomains appear)
- `open_ports` — list of integers: TCP ports found open during reconnaissance
- `sqli_payload` — the UNION-based SQL injection string from the credential-extracting query (raw `q` parameter value, URL-decoded)
- `sqli_tool` — offensive tool identified from HTTP User-Agent headers
- `reverse_shell_port` — TCP port the attacker listened on for the reverse shell callback
- `exfiltration_method` — short label for the exfiltration technique observed
- `compromised_credentials` — object mapping usernames to passwords extracted via SQL injection

### 2. `/app/report/exfiltrated_data.txt`

Fully decoded plaintext exfiltrated through the DNS tunnel. Reconstruct by extracting encoded subdomain labels, ordering fragments correctly, and decoding.

### 3. `/app/report/rule_evaluation.json`

Critically evaluate each candidate rule (R1 through R6) from `/app/proposed_rules/candidate_rules.txt` against the actual attack traffic in the PCAP. For each rule key (`R1` through `R6`), provide:

- `fires_on_attack_traffic` (boolean) — would this rule actually trigger on the observed attack packets? Consider the rule's target IP, port, protocol, direction, and content match conditions against what the PCAP contains.
- `verdict` — one of `"effective"`, `"partially_effective"`, or `"ineffective"`
- `primary_flaw` — brief description of the rule's main deficiency, or `"none"` if fully effective

### 4. `/app/report/detection_rules.rules`

Design a Snort-format IDS ruleset that detects all four attack phases observed in the capture: reconnaissance scanning, web application exploitation, reverse shell establishment, and DNS tunnel exfiltration. Each rule must include `msg`, `sid`, and appropriate content/threshold/flag options. Your rules should correct the deficiencies you identified in the candidate rules — aim for precision with minimal false positive risk while covering each distinct attack phase.